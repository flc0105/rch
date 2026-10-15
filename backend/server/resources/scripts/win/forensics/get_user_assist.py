SCRIPT_METADATA = {
    "name": "win/forensics/get_user_assist",
    "display_name": "UserAssist",
    "description": "Retrieve Windows Explorer application usage records.",
    "platforms": ["win"],
    "category": "Forensics",
    "params": []
}

import os
import json
import glob
import codecs
import ctypes
import struct
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    import winreg
except ImportError:
    print('{"error": "Windows platform support is required."}')
    raise SystemExit(1)


USERASSIST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"


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


def reg_time_to_string(value):
    return filetime_to_string(value)


def rot13(value):
    try:
        return codecs.decode(value, "rot_13")
    except Exception:
        return value


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


def parse_userassist_data(data):
    item = {
        "session_id": "",
        "run_count": "",
        "focus_count": "",
        "focus_time_ms": "",
        "last_execution_time": "",
        "raw_data": data.hex() if isinstance(data, bytes) else ""
    }

    if not isinstance(data, bytes):
        return item

    try:
        if len(data) >= 72:
            item["session_id"] = struct.unpack_from("<I", data, 0)[0]
            item["run_count"] = struct.unpack_from("<I", data, 4)[0]
            item["focus_count"] = struct.unpack_from("<I", data, 8)[0]
            item["focus_time_ms"] = struct.unpack_from("<I", data, 12)[0]
            item["last_execution_time"] = filetime_to_string(struct.unpack_from("<Q", data, 60)[0])

        elif len(data) >= 16:
            item["session_id"] = ""
            item["run_count"] = struct.unpack_from("<I", data, 4)[0]
            item["focus_count"] = ""
            item["focus_time_ms"] = ""
            item["last_execution_time"] = filetime_to_string(struct.unpack_from("<Q", data, 8)[0])

    except Exception:
        pass

    return item


def read_userassist(root, root_path, subkey):
    rows = []

    for guid in enum_subkeys(root, subkey):
        count_key = subkey + "\\" + guid + "\\Count"
        full_path = root_path + "\\" + USERASSIST_KEY + "\\" + guid + "\\Count"

        try:
            with winreg.OpenKey(root, count_key, 0, winreg.KEY_READ) as k:
                _, _, last_write_time = winreg.QueryInfoKey(k)

                i = 0
                while True:
                    try:
                        value_name, value_data, value_type = winreg.EnumValue(k, i)
                        i += 1

                        parsed = parse_userassist_data(value_data)

                        item = {
                            "path": full_path,
                            "last_write_time": reg_time_to_string(last_write_time),
                            "guid": guid,
                            "value_name": value_name,
                            "decoded_name": rot13(value_name),
                            "session_id": parsed["session_id"],
                            "run_count": parsed["run_count"],
                            "focus_count": parsed["focus_count"],
                            "focus_time_ms": parsed["focus_time_ms"],
                            "last_execution_time": parsed["last_execution_time"],
                            "raw_data": parsed["raw_data"]
                        }

                        rows.append(item)

                    except OSError:
                        break

        except Exception:
            pass

    return rows


def enum_hku():
    sids = []

    try:
        with winreg.OpenKey(winreg.HKEY_USERS, "") as hku:
            i = 0
            while True:
                try:
                    sid = winreg.EnumKey(hku, i)
                    i += 1

                    if sid.endswith("_Classes"):
                        continue

                    if sid == ".DEFAULT" or sid.startswith("S-1-5-"):
                        sids.append(sid)

                except OSError:
                    break
    except Exception:
        pass

    return sorted(set(sids))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_cmd(cmd):
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False
        )
        return p.returncode
    except Exception:
        return -1


def load_hive(hive_path, mount_name):
    return run_cmd(["reg.exe", "load", "HKU\\" + mount_name, hive_path]) == 0


def unload_hive(mount_name):
    run_cmd(["reg.exe", "unload", "HKU\\" + mount_name])


def find_ntuser_hives():
    users_dir = Path(os.environ.get("SystemDrive", "C:") + "\\Users")

    if not users_dir.exists():
        return []

    return [
        p for p in glob.glob(str(users_dir / "*" / "NTUSER.DAT"))
        if os.path.isfile(p)
    ]


result = []
seen = set()


def add_items(items, user):
    for item in items:
        key = (
            item.get("path", ""),
            item.get("value_name", ""),
            item.get("decoded_name", "")
        )

        if key in seen:
            continue

        seen.add(key)
        result.append({
            "user": user,
            "name": item["decoded_name"],
            "runs": item["run_count"] if item["run_count"] != "" else None,
            "focus_count": item["focus_count"] if item["focus_count"] != "" else None,
            "focus_ms": item["focus_time_ms"] if item["focus_time_ms"] != "" else None,
            "last_run": item["last_execution_time"] or None,
        })


for sid in enum_hku():
    add_items(read_userassist(
        winreg.HKEY_USERS,
        "HKU\\" + sid,
        sid + "\\" + USERASSIST_KEY
    ), sid)

if is_admin():
    for hive in find_ntuser_hives():
        mount_name = "_userassist_" + str(abs(hash(hive)))

        if load_hive(hive, mount_name):
            try:
                add_items(read_userassist(
                    winreg.HKEY_USERS,
                    "HKU\\" + mount_name,
                    mount_name + "\\" + USERASSIST_KEY
                ), Path(hive).parent.name)
            finally:
                unload_hive(mount_name)

result.sort(key=lambda item: (
    item["user"], item["last_run"] or "", item["name"]
), reverse=True)

print(json.dumps(result, ensure_ascii=False, indent=2))