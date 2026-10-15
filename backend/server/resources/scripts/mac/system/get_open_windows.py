
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/system/get_open_windows",
    "display_name": "Open Windows",
    "description": "List open macOS windows and their owning apps.",
    "platforms": ["mac"],
    "category": "System",
    "params": []
}

import json
import subprocess
from functools import lru_cache


@lru_cache(maxsize=None)
def get_app_path(pid):
    try:
        result = subprocess.run(
            ["lsof", "-p", str(pid), "-Fn"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    for line in result.stdout.splitlines():
        if line.startswith("n/") and ".app/" in line:
            return line[1:].split(".app/", 1)[0] + ".app"

    return ""


def read_windows():
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionAll,
        kCGNullWindowID,
    )

    raw_windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionAll,
        kCGNullWindowID,
    )

    windows = []
    seen = set()

    for window in raw_windows:
        title = (window.get("kCGWindowName") or "").strip()
        if not title:
            continue

        app = (window.get("kCGWindowOwnerName") or "Unknown").strip()
        pid = window.get("kCGWindowOwnerPID", 0)

        key = (pid, app, title)
        if key in seen:
            continue
        seen.add(key)

        windows.append({
            "app": app,
            "path": get_app_path(pid),
            "pid": pid,
            "title": title,
        })

    return windows


def main():
    try:
        output = read_windows()
    except Exception as exc:
        output = {"error": f"Failed to list windows: {exc}"}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()