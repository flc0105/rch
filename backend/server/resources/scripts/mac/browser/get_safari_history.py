SCRIPT_METADATA = {
    "name": "macos/browser/get_safari_history",
    "display_name": "Safari History",
    "description": "Retrieve Safari browsing history.",
    "platforms": ["mac"],
    "category": "Browser",
    "params": []
}

import os
import pwd
import json
import sqlite3
import subprocess
from pathlib import Path

MAX_RECORDS = 200

SKIP_USERS = {
    "Shared",
    ".localized",
}


def run_cmd(cmd):
    try:
        r = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=5,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def get_console_user():
    user = run_cmd(["/usr/bin/stat", "-f", "%Su", "/dev/console"])

    if user and user not in {"root", "_mbsetupuser", "loginwindow"}:
        return user

    return None


def get_home_for_user(username):
    try:
        return Path(pwd.getpwnam(username).pw_dir)
    except Exception:
        return Path("/Users") / username


def get_target_users():
    users = {}

    console = get_console_user()
    if console:
        users[console] = get_home_for_user(console)

    users_dir = Path("/Users")
    if users_dir.exists():
        for p in users_dir.iterdir():
            if not p.is_dir():
                continue
            if p.name in SKIP_USERS:
                continue
            if p.name.startswith("."):
                continue
            users[p.name] = p

    try:
        uid_user = pwd.getpwuid(os.getuid()).pw_name
        if uid_user != "root":
            users[uid_user] = Path.home()
    except Exception:
        pass

    return users


def table_columns(conn, table):
    try:
        return [
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
    except Exception:
        return []


def query_safari_db(history_path):
    rows = []

    conn = sqlite3.connect(f"file:{history_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    visit_cols = table_columns(conn, "history_visits")
    item_cols = table_columns(conn, "history_items")

    title_expr = "v.title" if "title" in visit_cols else "NULL"
    load_successful_expr = "v.load_successful" if "load_successful" in visit_cols else "NULL"
    visit_count_expr = "i.visit_count" if "visit_count" in item_cols else "NULL"

    sql = f"""
    SELECT
        datetime(v.visit_time + 978307200, 'unixepoch', 'localtime') AS time,
        {title_expr} AS title,
        i.url AS url,
        {visit_count_expr} AS visits,
        {load_successful_expr} AS loaded
    FROM history_visits v
    JOIN history_items i ON i.id = v.history_item
    ORDER BY v.visit_time DESC
    LIMIT ?
    """

    for row in conn.execute(sql, (MAX_RECORDS,)):
        visit_time = row["time"]
        rows.append({
            "time": visit_time.replace(" ", "T") if visit_time else None,
            "title": row["title"],
            "url": row["url"],
            "visits": row["visits"],
            "loaded": row["loaded"],
        })

    conn.close()
    return rows


def main():
    history = []
    errors = []

    for home in get_target_users().values():
        history_path = home / "Library/Safari/History.db"

        if not history_path.exists():
            continue

        try:
            history.extend(query_safari_db(history_path))
        except Exception as exc:
            errors.append(str(exc))

    result = {"error": "; ".join(errors)} if errors else history
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
