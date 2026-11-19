SCRIPT_METADATA = {
    "display_name": "Oracle SQL Query",
    "description": "Connect to an Oracle database on the selected device, execute SQL, and display the results.",
    "category": "Database",
    "platforms": ["win", "mac", "linux"],
    "execution": {
        "modes": {"allowed": ["inproc", "subprocess_pipe"], "default": "subprocess_pipe"},
        "output": {"allowed": ["collect", "stream"], "default": "collect"},
    },
    "params": [
        {
            "name": "connect_identifier", "label": "Database Connection", "type": "string",
            "required": True, "default": "//172.16.0.180:1521/NCC",
            "description": "TNS alias or //host:port/service_name",
        },
        {
            "name": "username", "label": "Database Username", "type": "string",
            "required": True, "default": "nccloud_test",
        },
        {
            "name": "password", "label": "Database Password", "type": "password",
            "required": True, "default": "b0nd1x2022",
            "keychain_picker": {
                "kind": "login",
                "bindings": {"username": "username", "secret_value": "password"},
            },
        },
        {
            "name": "sql", "label": "SQL", "type": "textarea", "required": True,
            "rows": 8, "default": "SELECT SYSDATE AS CURRENT_TIME FROM DUAL;",
            "description": "Execute one SQL statement or one PL/SQL block at a time.",
        },
        {
            "name": "json_output", "label": "Output JSON", "type": "boolean", "default": True,
            "description": "When enabled, output a JSON array; otherwise, output tab-separated text.",
        },
        {
            "name": "driver_mode", "label": "Driver Mode", "type": "select",
            "options": ["thin", "thick"], "default": "thin",
            "description": "Use Thin mode by default; older databases may require Thick mode and Oracle Client.",
        },
        {
            "name": "oracle_client_lib_dir", "label": "Oracle Client Library Directory", "type": "string",
            "default": "", "description": "For Thick mode only; enter the directory containing oci.dll.",
        },
        {
            "name": "timeout_seconds", "label": "Operation Timeout (seconds)", "type": "integer",
            "default": 120, "min": 1, "max": 3600,
            "description": "Timeout for each database network round-trip.",
        },
    ],
}

import base64
import csv
import datetime
import decimal
import json
import re
import sys


def convert_value(value):
    if hasattr(value, "read") and callable(value.read):
        value = value.read()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.time, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def execute_oracle_sql(params):
    try:
        import oracledb
    except ImportError as exc:
        raise RuntimeError(
            "The script Python on the target device does not have oracledb installed. Run: "
            f'"{sys.executable}" -m pip install oracledb -i https://mirrors.ustc.edu.cn/pypi/simple'
        ) from exc

    statement = str(params["sql"]).strip()
    if not statement:
        raise ValueError("SQL cannot be empty")

    # A standalone / line is a SQL*Plus execution command, not part of the PL/SQL block.
    lines = statement.splitlines()
    if lines and lines[-1].strip() == "/":
        statement = "\n".join(lines[:-1]).rstrip()
    # Identify PL/SQL blocks and definitions; their trailing semicolons are part of the statement.
    logical_head = re.sub(
        r"(?is)^\s*(?:(?:--[^\n]*(?:\n|$))|(?:/\*.*?\*/\s*))*",
        "", statement, count=1,
    )
    is_plsql = bool(re.match(
        r"(?is)^(?:BEGIN|DECLARE|CREATE\s+(?:OR\s+REPLACE\s+)?"
        r"(?:PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE)\b)",
        logical_head,
    ))
    if not is_plsql:
        statement = re.sub(r";\s*$", "", statement)
    if not statement.strip():
        raise ValueError("SQL cannot be empty")

    json_output = bool(params.get("json_output", True))
    if json_output and not re.match(
        r"(?is)^\s*(?:(?:--[^\n]*(?:\n|$))|(?:/\*.*?\*/\s*))*\s*(?:SELECT|WITH)\b",
        statement,
    ):
        raise ValueError("JSON mode supports only a single SELECT / WITH query; disable JSON output for other statements")

    mode = str(params.get("driver_mode") or "thin").strip().lower()
    if mode not in ("thin", "thick"):
        raise ValueError("Driver mode must be thin or thick")
    if mode == "thick":
        lib_dir = str(params.get("oracle_client_lib_dir") or "").strip()
        if lib_dir:
            oracledb.init_oracle_client(lib_dir=lib_dir)
        else:
            oracledb.init_oracle_client()

    timeout = int(params.get("timeout_seconds", 120))
    if not 1 <= timeout <= 3600:
        raise ValueError("Operation timeout must be between 1 and 3600 seconds")

    connection = oracledb.connect(
        user=str(params["username"]).strip(),
        password=str(params["password"]),
        dsn=str(params["connect_identifier"]).strip(),
    )
    try:
        connection.call_timeout = timeout * 1000
        with connection.cursor() as cursor:
            cursor.execute(statement)
            if cursor.description is None:
                if json_output:
                    raise ValueError("JSON mode supports only queries returning a result set")
                affected = cursor.rowcount
                connection.commit()
                if affected >= 0:
                    print("Execution succeeded. Rows affected: {}".format(affected))
                else:
                    print("Execution succeeded")
                return

            columns = [col[0] for col in cursor.description]
            if len(columns) != len(set(columns)) and json_output:
                raise ValueError("The query result contains duplicate column names; use distinct AS aliases")

            if json_output:
                rows = [
                    dict(zip(columns, (convert_value(v) for v in row)))
                    for row in cursor
                ]
                print(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False))
            else:
                writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
                writer.writerow(columns)
                for row in cursor:
                    writer.writerow([convert_value(v) for v in row])
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


execute_oracle_sql(kwargs)