
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/system/get_battery_status",
    "display_name": "Battery Status",
    "description": "Retrieve macOS battery charge and health information.",
    "platforms": ["mac"],
    "category": "System",
    "params": []
}

import json
import re
import subprocess


def get_battery_status():
    result = subprocess.run(
        ["pmset", "-g", "batt"],
        capture_output=True,
        text=True,
        check=True
    )

    output = result.stdout
    percentage = re.search(r"(\d+)%", output)

    if not percentage:
        raise RuntimeError("Battery information not available.")

    battery = {
        "percentage": int(percentage.group(1))
    }

    if "AC Power" in output:
        battery["state"] = "charging"
    elif "Battery Power" in output:
        battery["state"] = "discharging"

    remaining = re.search(r"(\d+):(\d+) remaining", output)
    if remaining:
        battery["remaining_minutes"] = (
            int(remaining.group(1)) * 60
            + int(remaining.group(2))
        )

    result = subprocess.run(
        ["system_profiler", "SPPowerDataType"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        cycle = re.search(r"Cycle Count:\s*(\d+)", result.stdout)
        if cycle:
            battery["cycle_count"] = int(cycle.group(1))

        condition = re.search(
            r"Condition:\s*([^\r\n]+)",
            result.stdout
        )
        if condition:
            battery["condition"] = condition.group(1).strip()

    return [battery]


def main():
    try:
        output = get_battery_status()
    except Exception as exc:
        output = {"error": str(exc)}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()