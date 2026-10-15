
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/device/volume_control",
    "display_name": "Volume Control",
    "description": "Get or set the macOS output volume.",
    "platforms": ["mac"],
    "category": "Device",
    "params": [
        {
            "name": "action",
            "type": "select",
            "required": False,
            "default": "get",
            "options": ["get", "set"],
            "description": "Choose whether to read or change the volume."
        },
        {
            "name": "level",
            "type": "number",
            "required": False,
            "default": 50,
            "description": "Output volume from 0 to 100 when setting."
        }
    ]
}

import subprocess


def main():
    action = kwargs.get("action", "get")

    try:
        if action == "get":
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"Current volume: {result.stdout.strip()}")

        elif action == "set":
            level = int(kwargs.get("level", 50))
            level = max(0, min(100, level))

            subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"Volume set to {level}")

        else:
            raise ValueError("Invalid action. Use 'get' or 'set'.")

    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()