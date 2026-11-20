#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "common/device/scan_bluetooth",
    "display_name": "Bluetooth Devices",
    "description": "List Bluetooth devices known to this computer.",
    "platforms": ["mac", "win"],
    "category": "Device",
    "params": [],
}

import json
import re
import subprocess

from client.runtime.sdk import context


WINDOWS_DEVICE_ID = re.compile(
    r"^BTH(?:ENUM|LE)\\DEV_([0-9A-F]{12})(?:\\|$)", re.IGNORECASE
)


def scan_mac():
    result = subprocess.run(
        ["system_profiler", "SPBluetoothDataType", "-json"],
        capture_output=True, text=True, check=True, timeout=45,
    )
    report = json.loads(result.stdout)
    sections = report["SPBluetoothDataType"]
    devices = {}

    for section in sections:
        for key, connected in (("device_connected", True), ("device_not_connected", False)):
            for entry in section.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                if isinstance(entry.get("device_name"), str):
                    candidates = [(entry["device_name"], entry)]
                else:
                    candidates = [(name, props) for name, props in entry.items()
                                  if isinstance(props, dict)]
                for name, props in candidates:
                    name = name.strip()
                    if not name:
                        continue
                    address = str(props.get("device_address") or "").upper()
                    identity = ("address", address) if address else ("name", name)
                    if identity in devices:
                        continue
                    devices[identity] = {
                        "name": name,
                        "address": address or None,
                        "connected": connected,
                        "type": props.get("device_minorType"),
                        "device_status": None,
                    }

    return sorted(devices.values(), key=lambda item: (not item["connected"], item["name"].casefold()))


def scan_win():
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$items = @(Get-PnpDevice -Class Bluetooth -ErrorAction Stop |
    Select-Object FriendlyName, InstanceId, Status)
ConvertTo-Json -InputObject $items -Depth 3 -Compress
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True, timeout=45,
    )
    raw = json.loads(result.stdout.lstrip("\ufeff"))
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]

    devices = {}
    for item in raw:
        instance_id = str(item.get("InstanceId") or "")
        match = WINDOWS_DEVICE_ID.match(instance_id)
        name = str(item.get("FriendlyName") or "").strip()
        if not match or not name:
            continue
        compact_address = match.group(1).upper()
        address = ":".join(compact_address[i:i + 2] for i in range(0, 12, 2))
        devices.setdefault(address, {
            "name": name,
            "address": address,
            "connected": None,
            "type": None,
            "device_status": item.get("Status"),
        })

    return sorted(devices.values(), key=lambda item: item["name"].casefold())


def main():
    try:
        os_alias = context.os_alias()
        if os_alias == "mac":
            output = scan_mac()
        elif os_alias == "win":
            output = scan_win()
        else:
            raise RuntimeError(f"Unsupported platform: {os_alias}")
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired,
            subprocess.CalledProcessError, RuntimeError) as exc:
        output = {"error": f"Failed to list Bluetooth devices: {exc}"}

    context.emit(output)


if __name__ == "__main__":
    main()