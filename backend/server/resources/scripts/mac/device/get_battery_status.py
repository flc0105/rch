#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/device/get_battery_status",
    "display_name": "Battery Status",
    "description": "Retrieve macOS battery charge and health information.",
    "platforms": ["mac"],
    "category": "Device",
    "params": []
}

import json
import re
import subprocess

from client.runtime.sdk import context


def get_battery_status():
    result = subprocess.run(
        ["pmset", "-g", "batt"],
        capture_output=True,
        text=True,
        check=True
    )

    battery_line = next(
        (
            line for line in result.stdout.splitlines()
            if re.search(r"\b(?:InternalBattery|ExternalBattery)-\d+\b", line)
        ),
        None
    )
    percentage = re.search(r"(\d{1,3})%\s*;", battery_line or "")
    if not percentage or int(percentage.group(1)) > 100:
        raise RuntimeError("Battery information not available.")

    battery = {"percentage": int(percentage.group(1))}
    status = battery_line[percentage.end():].lower()

    if "not charging" in status:
        battery["state"] = "not_charging"
    elif "discharging" in status:
        battery["state"] = "discharging"
    elif "finishing charge" in status:
        battery["state"] = "finishing_charge"
    elif "charging" in status:
        battery["state"] = "charging"
    elif "charged" in status:
        battery["state"] = "charged"

    remaining = re.search(r"(\d+):([0-5]\d)\s+(?:remaining|until full)\b", status)
    if remaining:
        minutes = int(remaining.group(1)) * 60 + int(remaining.group(2))
        if battery.get("state") == "discharging":
            battery["remaining_minutes"] = minutes
        elif battery.get("state") in ("charging", "finishing_charge"):
            battery["time_to_full_minutes"] = minutes

    result = subprocess.run(
        ["system_profiler", "SPPowerDataType", "-json"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        try:
            power_data = json.loads(result.stdout)
        except ValueError:
            power_data = {}
        if isinstance(power_data, dict):
            for item in power_data.get("SPPowerDataType", []):
                if not isinstance(item, dict):
                    continue
                health = item.get("sppower_battery_health_info")
                if not isinstance(health, dict):
                    continue
                cycles = health.get("sppower_battery_cycle_count")
                if cycles is not None:
                    try:
                        battery["cycle_count"] = int(cycles)
                    except (TypeError, ValueError):
                        pass
                condition = health.get("sppower_battery_health")
                if isinstance(condition, str) and condition.strip():
                    battery["condition"] = condition.strip()
                break

    return [battery]


def main():
    try:
        output = get_battery_status()
    except Exception as exc:
        output = {"error": str(exc)}

    context.emit(output)


if __name__ == "__main__":
    main()
