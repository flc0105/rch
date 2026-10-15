
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/system/get_running_apps",
    "display_name": "Running Apps",
    "description": "List running macOS graphical applications.",
    "platforms": ["mac"],
    "category": "System",
    "params": []
}

import json
import subprocess

EXCLUDED_APPS = {
    "Finder",
    "Dock",
    "SystemUIServer",
    "NotificationCenter",
    "Spotlight",
    "Siri"
}

APPLE_SCRIPT = r'''
tell application "System Events"
    set outputText to ""
    set appProcs to every application process whose background only is false

    repeat with proc in appProcs
        try
            set procName to name of proc
            set procPid to unix id of proc
            set procFrontmost to frontmost of proc
            set outputText to outputText & procName & "||" & procPid & "||" & procFrontmost & linefeed
        end try
    end repeat

    return outputText
end tell
'''


def get_process_paths():
    paths = {}

    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,comm="],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (
        OSError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError
    ):
        return paths

    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2:
            continue

        try:
            paths[int(fields[0])] = fields[1]
        except ValueError:
            continue

    return paths


def read_running_apps():
    result = subprocess.run(
        ["osascript", "-e", APPLE_SCRIPT],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )

    process_paths = get_process_paths()
    apps = []
    seen = set()

    for line in result.stdout.splitlines():
        fields = line.strip().rsplit("||", 2)
        if len(fields) != 3:
            continue

        name, pid_text, frontmost_text = (
            field.strip() for field in fields
        )

        if not name or name in EXCLUDED_APPS:
            continue

        try:
            pid = int(pid_text)
        except ValueError:
            pid = None

        key = (name, pid)
        if key in seen:
            continue
        seen.add(key)

        apps.append({
            "name": name,
            "pid": pid,
            "path": process_paths.get(pid),
            "frontmost": frontmost_text.lower() == "true",
        })

    return apps


def main():
    try:
        output = read_running_apps()
    except (
        OSError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError
    ) as exc:
        output = {"error": f"Failed to list running apps: {exc}"}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()