#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/security/get_full_disk_access",
    "display_name": "Full Disk Access",
    "description": "Retrieve macOS Full Disk Access permissions.",
    "platforms": ["mac"],
    "category": "Security",
    "params": []
}

import datetime as dt
import json
import sqlite3
from contextlib import closing
from pathlib import Path

SERVICE = "kTCCServiceSystemPolicyAllFiles"

STATUS_MAP = {
    0: "denied",
    1: "unknown_or_prompt",
    2: "allowed",
    3: "limited",
}

CLIENT_TYPE_MAP = {
    0: "bundle_id",
    1: "absolute_path",
}


def to_local_time(value):
    if value is None:
        return None

    try:
        timestamp = float(value)
        if timestamp <= 0:
            return None

        return dt.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def get_user_homes():
    homes = {Path.home()}
    users_dir = Path("/Users")

    if users_dir.is_dir():
        homes.update(
            path for path in users_dir.iterdir()
            if path.is_dir()
            and not path.name.startswith(".")
            and path.name != "Shared"
        )

    return sorted(path for path in homes if path.is_dir())


def find_databases():
    databases = []

    system_db = Path("/Library/Application Support/com.apple.TCC/TCC.db")

    if system_db.is_file():
        databases.append(("system", "system", system_db))

    for home in get_user_homes():
        db_path = home / "Library/Application Support/com.apple.TCC/TCC.db"

        if db_path.is_file():
            databases.append(("user", home.name, db_path))

    return databases


def read_permissions(scope, owner, db_path):
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT
                client,
                client_type,
                auth_value,
                auth_reason,
                flags,
                last_modified
            FROM access
            WHERE service = ?
            ORDER BY last_modified DESC, client_type, client
        """, (SERVICE,))

        return [
            {
                "time": to_local_time(row["last_modified"]),
                "scope": scope,
                "owner": owner,
                "client": row["client"],
                "client_type": CLIENT_TYPE_MAP.get(
                    row["client_type"], "unknown"
                ),
                "status": STATUS_MAP.get(
                    row["auth_value"], "unknown"
                ),
                "allowed": row["auth_value"] == 2,
                "reason": row["auth_reason"],
                "flags": row["flags"],
            }
            for row in rows
        ]


def main():
    permissions = []
    databases = find_databases()
    successful_reads = 0
    last_error = None

    for scope, owner, db_path in databases:
        try:
            permissions.extend(read_permissions(scope, owner, db_path))
            successful_reads += 1
        except (OSError, sqlite3.Error) as exc:
            last_error = str(exc)

    if databases and successful_reads == 0:
        output = {
            "error": f"Failed to read Full Disk Access permissions: {last_error}"
        }
    else:
        output = permissions

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()