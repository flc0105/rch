#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/security/get_quarantine_history",
    "display_name": "Quarantine History",
    "description": "Retrieve recent macOS quarantine events.",
    "platforms": ["mac"],
    "category": "Security",
    "params": []
}

import datetime as dt
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

MAX_RECORDS = 500
COCOA_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)


def to_local_time(value):
    if value is None:
        return None

    try:
        timestamp = COCOA_EPOCH + dt.timedelta(seconds=float(value))
        return timestamp.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError, OverflowError):
        return None


def copy_database(source, directory):
    copied = directory / source.name
    shutil.copy2(source, copied)

    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, directory / f"{source.name}{suffix}")

    return copied


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
    databases = set()

    for home in get_user_homes():
        main_db = home / "Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2"

        if main_db.is_file():
            databases.add((home.name, main_db))

        containers_dir = home / "Library/Containers"

        if containers_dir.is_dir():
            for db_path in containers_dir.glob(
                "*/Data/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2"
            ):
                if db_path.is_file():
                    databases.add((home.name, db_path))

    return sorted(databases, key=lambda item: str(item[1]))


def read_events(username, db_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        database = copy_database(db_path, Path(temp_dir))

        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
                SELECT
                    LSQuarantineEventIdentifier,
                    LSQuarantineTimeStamp,
                    LSQuarantineAgentBundleIdentifier,
                    LSQuarantineAgentName,
                    LSQuarantineTypeNumber,
                    LSQuarantineDataURLString,
                    LSQuarantineOriginURLString
                FROM LSQuarantineEvent
                ORDER BY LSQuarantineTimeStamp DESC
                LIMIT ?
            """, (MAX_RECORDS,))

            return [
                {
                    "time": to_local_time(row["LSQuarantineTimeStamp"]),
                    "id": row["LSQuarantineEventIdentifier"],
                    "agent": row["LSQuarantineAgentName"],
                    "bundle_id": row["LSQuarantineAgentBundleIdentifier"],
                    "type": row["LSQuarantineTypeNumber"],
                    "url": row["LSQuarantineDataURLString"],
                    "origin_url": row["LSQuarantineOriginURLString"],
                    "user": username,
                }
                for row in rows
            ]


def main():
    events = []
    successful_reads = 0
    last_error = None
    databases = find_databases()

    for username, db_path in databases:
        try:
            events.extend(read_events(username, db_path))
            successful_reads += 1
        except (OSError, sqlite3.Error, ValueError) as exc:
            last_error = str(exc)

    if databases and successful_reads == 0:
        output = {"error": f"Failed to read quarantine history: {last_error}"}
    else:
        output = sorted(
            events,
            key=lambda item: item["time"] or "",
            reverse=True
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()