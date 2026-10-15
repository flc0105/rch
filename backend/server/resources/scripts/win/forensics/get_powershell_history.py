
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "win/shell/get_powershell_history",
    "display_name": "PowerShell History",
    "description": "Read PowerShell command history from local user profiles.",
    "platforms": ["win"],
    "category": "Shell",
    "params": []
}

import os
import glob
from pathlib import Path
from datetime import datetime


def read_lines(path):
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, errors="replace") as file:
                return file.read().splitlines()
        except Exception:
            pass
    return []


def file_mtime(path):
    try:
        return datetime.fromtimestamp(
            os.path.getmtime(path)
        ).isoformat(sep=" ", timespec="seconds")
    except Exception:
        return ""


def get_profiles():
    users_dir = Path(os.environ.get("SystemDrive", "C:") + "\\Users")
    profiles = []

    if users_dir.exists():
        for profile in users_dir.iterdir():
            if profile.is_dir():
                profiles.append(profile)

    current = os.environ.get("USERPROFILE")
    if current:
        profile = Path(current)
        if profile not in profiles:
            profiles.append(profile)

    return profiles


def find_history_files(profile):
    patterns = [
        profile / "AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/*_history.txt",
        profile / "AppData/Roaming/Microsoft/PowerShell/PSReadLine/*_history.txt",
        profile / "Documents/PowerShell/PSReadLine/*_history.txt",
        profile / "Documents/WindowsPowerShell/PSReadLine/*_history.txt",
    ]

    files = []
    for pattern in patterns:
        files.extend(glob.glob(str(pattern)))

    return [path for path in files if os.path.isfile(path)]


def main():
    history_files = []
    seen = set()

    for profile in get_profiles():
        for path in find_history_files(profile):
            key = os.path.abspath(path).lower()
            if key not in seen:
                seen.add(key)
                history_files.append(path)

    if not history_files:
        print("No PowerShell history files found.")
        return

    for path in history_files:
        print("=" * 80)
        print("Path:", path)
        print("Last Modified:", file_mtime(path))
        print("=" * 80)

        for command in read_lines(path):
            print(command)

        print()


if __name__ == "__main__":
    main()