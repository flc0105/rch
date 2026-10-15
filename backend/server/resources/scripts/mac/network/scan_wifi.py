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

BSSID_PATTERN = re.compile(
    r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}"
)


def parse_networks(output):
    networks = []

    for line in output.splitlines()[1:]:
        parts = line.split()

        bssid_index = next(
            (
                index
                for index, part in enumerate(parts)
                if BSSID_PATTERN.fullmatch(part)
            ),
            None
        )

        if bssid_index is None or len(parts) <= bssid_index + 1:
            continue

        try:
            rssi = int(parts[bssid_index + 1])
        except ValueError:
            continue

        networks.append({
            "ssid": " ".join(parts[:bssid_index]) or "(hidden)",
            "signal": max(0, min(100, 2 * (rssi + 100))),
            "security": " ".join(parts[bssid_index + 5:]),
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
                or network["signal"] > strongest[ssid]["signal"]
            ):
                strongest[ssid] = network

        output = sorted(
            strongest.values(),
            key=lambda item: item["signal"],
            reverse=True
        )

    except (OSError, subprocess.CalledProcessError) as exc:
        output = {"error": f"Failed to scan Wi-Fi networks: {exc}"}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()