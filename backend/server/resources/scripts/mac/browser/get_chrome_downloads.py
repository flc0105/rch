SCRIPT_METADATA = {
    "name": "mac/browser/get_chrome_downloads",
    "display_name": "Chrome Downloads",
    "description": "Retrieve recent Chrome download history.",
    "platforms": ["mac"],
    "category": "Browser",
    "params": []
}

import json
import shutil
import sqlite3
import tempfile
import datetime as dt
from pathlib import Path

MAX_RECORDS = 100
CHROMIUM_EPOCH_OFFSET = 11644473600

HISTORY_PATH = (
    Path.home()
    / "Library/Application Support/Google/Chrome/Default/History"
)


def chrome_time_to_local_iso(chrome_time):
    if chrome_time is None:
        return None

    unix_ts = chrome_time / 1_000_000 - CHROMIUM_EPOCH_OFFSET
    return dt.datetime.fromtimestamp(unix_ts).isoformat(timespec="seconds")


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def copy_history_db(src, tmpdir):
    copied = tmpdir / "History"
    shutil.copy2(src, copied)

    for suffix in ["-wal", "-shm"]:
        sidecar = Path(str(src) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, tmpdir / ("History" + suffix))

    return copied


def main():
    downloads = []

    if not HISTORY_PATH.exists():
        print(json.dumps(downloads, ensure_ascii=False, indent=2))
        return

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        copied_history = copy_history_db(HISTORY_PATH, tmpdir)

        conn = sqlite3.connect(f"file:{copied_history}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        target_expr = (
            "d.target_path"
            if column_exists(conn, "downloads", "target_path")
            else "NULL"
        )

        current_expr = (
            "d.current_path"
            if column_exists(conn, "downloads", "current_path")
            else "NULL"
        )

        sql = f"""
        SELECT
            d.start_time,
            {target_expr} AS target_path,
            {current_expr} AS current_path,
            u.url
        FROM downloads d
        LEFT JOIN downloads_url_chains u ON d.id = u.id
        ORDER BY d.start_time DESC
        LIMIT ?
        """

        for row in conn.execute(sql, (MAX_RECORDS,)):
            downloads.append({
                "time": chrome_time_to_local_iso(row["start_time"]),
                "path": row["target_path"],
                "current_path": row["current_path"],
                "url": row["url"],
            })

        conn.close()

    print(json.dumps(downloads, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
