
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/system/get_launch_items",
    "display_name": "Launch Items",
    "description": "List macOS launch agents, daemons, and login items.",
    "platforms": ["mac"],
    "category": "System",
    "params": []
}

import json
import plistlib
import subprocess
from pathlib import Path

LAUNCH_LOCATIONS = (
    (Path.home() / "Library/LaunchAgents", "LaunchAgent", "user"),
    (Path("/Library/LaunchAgents"), "LaunchAgent", "system"),
    (Path("/Library/LaunchDaemons"), "LaunchDaemon", "system"),
)


def read_launch_items():
    items = []

    for directory, item_type, scope in LAUNCH_LOCATIONS:
        if not directory.is_dir():
            continue

        for plist_path in directory.glob("*.plist"):
            try:
                with plist_path.open("rb") as file:
                    data = plistlib.load(file)
            except (OSError, ValueError, TypeError):
                continue

            items.append({
                "name": data.get("Label", plist_path.stem),
                "path": str(plist_path),
                "type": item_type,
                "scope": scope,
            })

    return items


def read_login_items():
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get the name of every login item'
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (
        OSError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError
    ):
        return []

    return [
        {
            "name": name.strip(),
            "path": "",
            "type": "LoginItem",
            "scope": "user",
        }
        for name in result.stdout.strip().split(",")
        if name.strip()
    ]


def main():
    try:
        output = read_launch_items() + read_login_items()
    except OSError as exc:
        output = {"error": f"Failed to read launch items: {exc}"}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()