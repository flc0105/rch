
SCRIPT_METADATA = {
    "name": "win/device/get_usb_history",
    "display_name": "USB Storage History",
    "description": "Retrieve previously connected USB storage devices.",
    "platforms": ["win"],
    "category": "Device",
    "params": []
}

import os
import re
import json
import struct
from datetime import datetime, timezone, timedelta

try:
    import winreg
except ImportError:
    print('{"error": "Windows platform support is required."}')
    raise SystemExit(1)


USBSTOR_KEY = r"SYSTEM\CurrentControlSet\Enum\USBSTOR"
MOUNTED_DEVICES_KEY = r"SYSTEM\MountedDevices"
PROPERTY_GUID = "{83da6326-97a6-4088-9453-a1923f573b29}"


def filetime_to_string(value):
    try:
        if not value:
            return ""

        base = datetime(1601, 1, 1, tzinfo=timezone.utc)
        dt = base + timedelta(microseconds=value / 10)

        if dt.year < 1980 or dt.year > 2100:
            return ""

        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


def enum_subkeys(root, subkey):
    rows = []

    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    rows.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break
    except Exception:
        pass

    return rows


def read_value(root, subkey, name):
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            value, _ = winreg.QueryValueEx(k, name)
            return value
    except Exception:
        return ""


def parse_device_name(device_name):
    result = {
        "device_type": "",
        "vendor": "",
        "product": "",
        "revision": ""
    }

    m = re.match(r"([^&]+)&Ven_(.*?)&Prod_(.*?)&Rev_(.*)", device_name, re.I)
    if not m:
        result["device_type"] = device_name
        return result

    result["device_type"] = m.group(1).replace("_", " ").strip()
    result["vendor"] = m.group(2).replace("_", " ").strip()
    result["product"] = m.group(3).replace("_", " ").strip()
    result["revision"] = m.group(4).replace("_", " ").strip()

    return result


def clean_serial(instance_id):
    if "&" in instance_id:
        base, tail = instance_id.rsplit("&", 1)
        if tail.isdigit():
            return base

    return instance_id


def read_property_time(root, instance_subkey, prop_id):
    prop_subkey = instance_subkey + r"\Properties" + "\\" + PROPERTY_GUID + "\\" + prop_id

    try:
        with winreg.OpenKey(root, prop_subkey, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(k, i)
                    i += 1

                    if isinstance(value, bytes) and len(value) >= 8:
                        ts = filetime_to_string(struct.unpack("<Q", value[:8])[0])
                        if ts:
                            return ts

                    if isinstance(value, int):
                        ts = filetime_to_string(value)
                        if ts:
                            return ts

                except OSError:
                    break
    except Exception:
        pass

    return ""


def decode_mounted_device_data(data):
    if not isinstance(data, bytes):
        return ""

    try:
        text = data.decode("utf-16le", errors="ignore")
        text = text.replace("\x00", "").strip()
        text = "".join(c for c in text if c.isprintable()).strip()
        return text
    except Exception:
        return ""


def read_mounted_devices():
    rows = []

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, MOUNTED_DEVICES_KEY, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                    i += 1

                    target = decode_mounted_device_data(value)

                    rows.append({
                        "name": name,
                        "target": target
                    })

                except OSError:
                    break
    except Exception:
        pass

    return rows


def find_mount_points(device_name, instance_id, mounted_devices):
    rows = []
    needle = ("USBSTOR#" + device_name + "#" + instance_id).lower()

    for item in mounted_devices:
        target = item.get("target", "")

        if needle in target.lower():
            rows.append({
                "name": item.get("name", ""),
                "target": target
            })

    return rows


def split_mount_points(mount_points):
    drive_letters = []
    volume_guids = []

    for item in mount_points:
        name = item.get("name", "")

        if name.startswith("\\DosDevices\\"):
            drive_letters.append(name.removeprefix("\\DosDevices\\"))

        if name.startswith(r"\??\Volume{"):
            volume_guids.append(name.removeprefix("\\??\\"))

    return drive_letters, volume_guids


mounted_devices = read_mounted_devices()
result = []

for device_name in enum_subkeys(winreg.HKEY_LOCAL_MACHINE, USBSTOR_KEY):
    device_subkey = USBSTOR_KEY + "\\" + device_name
    parsed = parse_device_name(device_name)

    for instance_id in enum_subkeys(winreg.HKEY_LOCAL_MACHINE, device_subkey):
        instance_subkey = device_subkey + "\\" + instance_id
        serial_number = clean_serial(instance_id)
        mount_points = find_mount_points(device_name, instance_id, mounted_devices)
        drive_letters, volume_guids = split_mount_points(mount_points)

        item = {
            "name": (
                read_value(winreg.HKEY_LOCAL_MACHINE, instance_subkey, "FriendlyName")
                or parsed["product"]
                or device_name
            ),
            "friendly_name": read_value(
                winreg.HKEY_LOCAL_MACHINE, instance_subkey, "FriendlyName"
            ),
            "vendor": parsed["vendor"],
            "product": parsed["product"],
            "type": parsed["device_type"],
            "serial": serial_number,
            "drives": drive_letters,
            "volumes": volume_guids,
            "first_installed": None,
            "last_connected": None,
            "last_removed": None,
        }

        item["first_installed"] = (
            read_property_time(winreg.HKEY_LOCAL_MACHINE, instance_subkey, "00000065")
            or read_property_time(winreg.HKEY_LOCAL_MACHINE, instance_subkey, "00000064")
        )
        item["last_connected"] = read_property_time(
            winreg.HKEY_LOCAL_MACHINE, instance_subkey, "00000066"
        )
        item["last_removed"] = read_property_time(
            winreg.HKEY_LOCAL_MACHINE, instance_subkey, "00000067"
        )

        for field in ("first_installed", "last_connected", "last_removed"):
            item[field] = item[field] or None

        result.append(item)

result.sort(key=lambda item: (
    item["vendor"], item["product"], item["serial"], item["type"]
))

print(json.dumps(result, ensure_ascii=False, indent=2))