#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "common/browser/get_chrome_downloads",
    "display_name": "Chrome Downloads",
    "description": "Retrieve recent Chrome download history.",
    "platforms": ["mac", "win"],
    "category": "Browser",
    "params": [],
}

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from client.runtime.sdk import context
from core.utils.formatting import timestamp_to_readable_time


MAX_RECORDS = 100
CHROMIUM_EPOCH_OFFSET = 11644473600


def history_path(os_alias):
    if os_alias == "mac":
        root = Path.home() / "Library/Application Support/Google/Chrome"
    elif os_alias == "win":
        local_app_data = os.environ.get("LOCALAPPDATA")
        root = (Path(local_app_data) if local_app_data
                else Path.home() / "AppData/Local") / "Google/Chrome/User Data"
    else:
        raise ValueError(f"Unsupported platform: {os_alias}")
    return root / "Default/History"


def chrome_time_to_local_iso(chrome_time):
    if not chrome_time:
        return None
    try:
        timestamp = int(chrome_time) / 1_000_000 - CHROMIUM_EPOCH_OFFSET
        return timestamp_to_readable_time(timestamp)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def copy_history_db(source, folder):
    copied = folder / "History"
    shutil.copy2(source, copied)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(source) + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, folder / ("History" + suffix))
    return copied


def scan_downloads(os_alias):
    source = history_path(os_alias)
    if not source.is_file():
        return []

    with tempfile.TemporaryDirectory() as temp:
        copied = copy_history_db(source, Path(temp))
        with closing(sqlite3.connect(str(copied), timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            target_expr = ("d.target_path" if column_exists(conn, "downloads", "target_path")
                           else "NULL")
            current_expr = ("d.current_path" if column_exists(conn, "downloads", "current_path")
                            else "NULL")
            sql = f"""
                SELECT d.start_time,
                       {target_expr} AS target_path,
                       {current_expr} AS current_path,
                       (SELECT u.url FROM downloads_url_chains AS u
                        WHERE u.id = d.id
                        ORDER BY u.chain_index DESC LIMIT 1) AS url
                FROM downloads AS d
                ORDER BY d.start_time DESC, d.id DESC
                LIMIT ?
            """
            return [{
                "time": chrome_time_to_local_iso(row["start_time"]),
                "path": row["target_path"],
                "current_path": row["current_path"],
                "url": row["url"],
            } for row in conn.execute(sql, (MAX_RECORDS,))]


def main():
    try:
        output = scan_downloads(context.os_alias())
    except (OSError, ValueError, sqlite3.Error) as exc:
        output = {"error": f"Failed to read Chrome downloads: {exc}"}
    context.emit(output)


if __name__ == "__main__":
    main()