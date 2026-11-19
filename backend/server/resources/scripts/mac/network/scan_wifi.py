#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/network/scan_wifi",
    "display_name": "Scan Wi-Fi",
    "description": "Scan nearby Wi-Fi networks.",
    "platforms": ["mac"],
    "category": "Network",
    "params": []
}

import json
import re
import subprocess

AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"

BSSID_PATTERN = re.compile(r"(?:^|\s+)(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
SCAN_ROW = re.compile(
    r"^\s*(?P<identity>.*?)\s+"
    r"(?P<rssi>-?\d{1,3})\s+"
    r"\d+(?:,[+-]?\d+)?\s+[YN]\s+(?:--|[A-Za-z]{2})\s+"
    r"(?P<security>.*?)\s*$"
)


def parse_networks(output):
    networks = []

    for line in output.splitlines():
        match = SCAN_ROW.match(line)
        if not match:
            continue

        networks.append({
            "ssid": BSSID_PATTERN.sub("", match.group("identity").strip()).strip() or "(hidden)",
            "rssi": int(match.group("rssi")),
            "security": match.group("security").strip(),
        })

    return networks


def main():
    try:
        result = subprocess.run(
            [AIRPORT, "-s"],
            capture_output=True,
            text=True,
            check=True
        )

        strongest = {}

        for network in parse_networks(result.stdout):
            ssid = network["ssid"]

            if (
                ssid not in strongest
                or network["rssi"] > strongest[ssid]["rssi"]
            ):
                strongest[ssid] = network

        output = [
            {
                "ssid": network["ssid"],
                "signal": max(0, min(100, 2 * (network["rssi"] + 100))),
                "security": network["security"],
            }
            for network in sorted(
                strongest.values(),
                key=lambda item: item["rssi"],
                reverse=True
            )
        ]

    except (OSError, subprocess.CalledProcessError) as exc:
        output = {"error": f"Failed to scan Wi-Fi networks: {exc}"}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()