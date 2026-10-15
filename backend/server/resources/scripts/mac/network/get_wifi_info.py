#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/network/get_wifi_info",
    "display_name": "Wi-Fi Info",
    "description": "Retrieve the current and saved Wi-Fi networks.",
    "platforms": ["mac"],
    "category": "Network",
    "params": []
}

import json
import re
import subprocess

UNAVAILABLE = "未连接或无法获取"


def get_wifi_interface():
    try:
        output = subprocess.check_output(
            ["networksetup", "-listallhardwareports"],
            text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    lines = output.splitlines()

    for index, line in enumerate(lines[:-1]):
        if "AirPort" in line or "Wi-Fi" in line:
            next_line = lines[index + 1]

            if "Device:" in next_line:
                return next_line.split(":", 1)[1].strip()

    return None


def get_current_wifi(interface):
    if not interface:
        return UNAVAILABLE

    try:
        output = subprocess.check_output(
            ["networksetup", "-getairportnetwork", interface],
            text=True
        )

        if "Current Wi-Fi Network:" in output:
            return output.split(":", 1)[1].strip()

    except (OSError, subprocess.CalledProcessError):
        pass

    return UNAVAILABLE


def get_known_wifi(interface):
    networks = []

    if interface:
        try:
            output = subprocess.check_output(
                [
                    "networksetup",
                    "-listpreferredwirelessnetworks",
                    interface
                ],
                text=True
            )

            networks = [
                line.strip()
                for line in output.splitlines()[1:]
                if line.strip()
            ]

        except (OSError, subprocess.CalledProcessError):
            pass

    if not networks:
        try:
            output = subprocess.check_output(
                [
                    "defaults",
                    "read",
                    "/Library/Preferences/SystemConfiguration/com.apple.airport.preferences"
                ],
                text=True,
                stderr=subprocess.DEVNULL
            )

            networks = re.findall(
                r'SSIDString = "([^"]+)"',
                output
            )

        except (OSError, subprocess.CalledProcessError):
            pass

    return sorted(set(networks), key=str.lower)


def main():
    interface = get_wifi_interface()

    output = {
        "current_network": get_current_wifi(interface),
        "known_networks": get_known_wifi(interface),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()