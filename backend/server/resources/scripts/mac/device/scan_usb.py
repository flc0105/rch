#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/device/scan_usb",
    "display_name": "Scan USB",
    "description": "Scan connected USB devices.",
    "platforms": ["mac"],
    "category": "Device",
    "params": []
}

import json
import subprocess


def flatten_devices(items, path=""):
    devices = []

    for item in items:
        name = item.get("_name", "Unknown")
        current_path = f"{path} > {name}" if path else name

        devices.append({
            "name": name,
            "vendor": item.get("manufacturer", "") or "",
            "vendor_id": item.get("vendor_id", "") or "",
            "product_id": item.get("product_id", "") or "",
            "serial": item.get("serial_num", "") or "",
            "path": current_path,
        })

        if "_items" in item:
            devices.extend(
                flatten_devices(item["_items"], current_path)
            )

    return devices


def main():
    try:
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType", "-json"],
            capture_output=True,
            text=True,
            check=True,
        )

        data = json.loads(result.stdout)
        devices = flatten_devices(data.get("SPUSBDataType", []))

        devices = [
            device for device in devices
            if device["vendor"] or device["product_id"]
        ]

        output = sorted(
            devices,
            key=lambda device: (
                device["name"].lower(),
                device["path"].lower()
            )
        )

    except (
        OSError,
        subprocess.CalledProcessError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        output = {"error": f"Failed to scan USB devices: {exc}"}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()