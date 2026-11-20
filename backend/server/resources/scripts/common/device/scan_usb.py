#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "common/device/scan_usb",
    "display_name": "Scan USB",
    "description": "Scan connected USB devices.",
    "platforms": ["mac", "win"],
    "category": "Device",
    "params": [],
}

import json
import re
import subprocess

from client.runtime.sdk import context


USB_INSTANCE = re.compile(
    r"^USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})(?=\\|&)",
    re.IGNORECASE,
)


def flatten_devices(items, path=""):
    devices = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("_name") or "Unknown"
        current_path = f"{path} > {name}" if path else name
        if item.get("vendor_id") or item.get("product_id"):
            devices.append({
                "name": name,
                "vendor": item.get("manufacturer") or "",
                "vendor_id": item.get("vendor_id") or "",
                "product_id": item.get("product_id") or "",
                "serial": item.get("serial_num") or "",
                "path": current_path,
            })
        children = item.get("_items")
        if isinstance(children, list):
            devices.extend(flatten_devices(children, current_path))
    return devices


def scan_mac():
    result = subprocess.run(
        ["system_profiler", "SPUSBDataType", "-json"],
        capture_output=True, text=True, check=True, timeout=60,
    )
    data = json.loads(result.stdout)
    return flatten_devices(data.get("SPUSBDataType", []))


def scan_win():
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop |
    Where-Object {
        $_.InstanceId -match '^USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}(?:\\|&)' -and
        $_.InstanceId -notmatch '&MI_[0-9A-F]{2}(?:\\|&)'
    } |
    ForEach-Object {
        $device = $_
        $reported = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName 'DEVPKEY_Device_BusReportedDeviceDesc' -ErrorAction SilentlyContinue
        $location = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName 'DEVPKEY_Device_LocationPaths' -ErrorAction SilentlyContinue
        $locationPath = $null
        if ($location) {
            foreach ($candidate in @($location.Data)) {
                if ($candidate -is [string] -and $candidate.Trim()) {
                    $locationPath = $candidate
                    break
                }
            }
        }
        $name = if ($reported -and $reported.Data -is [string] -and $reported.Data.Trim()) {
            $reported.Data.Trim()
        } else {
            [string]$device.FriendlyName
        }
        [PSCustomObject]@{
            FriendlyName = $name
            InstanceId = [string]$device.InstanceId
            Status = [string]$device.Status
            DeviceClass = [string]$device.Class
            LocationPath = $locationPath
        }
    })
ConvertTo-Json -InputObject $devices -Depth 3 -Compress
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True, timeout=60,
    )
    records = json.loads(result.stdout.lstrip("\ufeff"))
    if not isinstance(records, list):
        raise ValueError("Unexpected Windows USB device response.")
    devices = []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        instance_id = str(entry.get("InstanceId") or "")
        match = USB_INSTANCE.match(instance_id)
        if not match or "&MI_" in instance_id.split("\\", 2)[1].upper():
            continue
        device = {
            "name": str(entry.get("FriendlyName") or "Unknown").strip() or "Unknown",
            "vendor_id": match.group(1).upper(),
            "product_id": match.group(2).upper(),
            "path": instance_id,
        }
        for field, value in (
            ("status", entry.get("Status")),
            ("device_class", entry.get("DeviceClass")),
            ("location_path", entry.get("LocationPath")),
        ):
            if isinstance(value, str) and value.strip():
                device[field] = value.strip()
        devices.append(device)
    return devices


def main():
    try:
        os_alias = context.os_alias()
        if os_alias == "mac":
            devices = scan_mac()
        elif os_alias == "win":
            devices = scan_win()
        else:
            raise RuntimeError(f"Unsupported platform: {os_alias}")
        output = sorted(
            devices, key=lambda item: (item["name"].casefold(), item["path"].casefold())
        )
    except (OSError, ValueError, TypeError, KeyError, RuntimeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        output = {"error": f"Failed to scan USB devices: {exc}"}
    context.emit(output)


if __name__ == "__main__":
    main()