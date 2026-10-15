#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/elevate/launch_as_admin",
    "display_name": "Launch as Admin",
    "description": "Launch a client session with macOS administrator authorization.",
    "platforms": ["mac"],
    "category": "Elevate",
    "params": []
}

import subprocess

from client.runtime.sdk import variables

APPLE_SCRIPT = """
on run argv
    set launchCommand to item 1 of argv
    set shellCommand to "(" & launchCommand & ") </dev/null >/dev/null 2>&1 &"
    do shell script shellCommand with administrator privileges
end run
"""

def main():
    command = variables.get("rch:launch_command")

    if not isinstance(command, str) or not command.strip():
        print("Error: Launch command is missing.")
        raise SystemExit(1)

    try:
        process = subprocess.Popen(
            ["osascript", "-e", APPLE_SCRIPT, command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

        print(f"Administrator authorization requested. PID: {process.pid}")

    except OSError as exc:
        print(f"Error: Failed to launch administrator prompt: {exc}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()