SCRIPT_METADATA = {
    "name": "win/forensics/get_recent_docs",
    "display_name": "Recent Docs",
    "description": "Retrieve recently accessed document records from Windows Explorer.",
    "platforms": ["win"],
    "category": "Forensics",
    "params": []
}

import os
import json
import glob
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


RECENTDOCS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs"


def reg_time_to_string(value):
    try:
        base = datetime(1601, 1, 1, tzinfo=timezone.utc)
        dt = base + timedelta(microseconds=value / 10)
        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


def parse_mru_listex(data):
    order = []

    if not isinstance(data, bytes):
        return order

    for i in range(0, len(data), 4):
        if i + 4 > len(data):
            break

        n = struct.unpack("<I", data[i:i + 4])[0]

        if n == 0xFFFFFFFF:
            break

        order.append(str(n))

    return order


def read_mru_order(root, subkey):
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            value, value_type = winreg.QueryValueEx(k, "MRUListEx")
            if value_type == winreg.REG_BINARY:
                return parse_mru_listex(value)
    except Exception:
        pass

    return []


def extract_filename(data):
    if not isinstance(data, bytes) or len(data) < 4:
        return ""

    try:
        end = data.find(b"\x00\x00", 2)

        while end != -1 and end % 2 != 0:
            end = data.find(b"\x00\x00", end + 1)

        if end == -1:
            return ""

        text = data[:end].decode("utf-16le", errors="ignore")
        text = text.replace("\x00", "").strip()

        if not text:
            return ""

        text = "".join(
            c for c in text
            if c.isprintable() and c not in "\r\n\t"
        ).strip()

        if not text:
            return ""

        if len(text) > 260:
            return ""

        return text
    except Exception:
        return ""


def read_recentdocs_tree(root, full_path, subkey):
    rows = []

    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            subkey_count, value_count, last_write_time = winreg.QueryInfoKey(k)

            mru_order = read_mru_order(root, subkey)
            mru_index = {value_name: index for index, value_name in enumerate(mru_order)}

            i = 0
            while True:
                try:
                    value_name, value_data, value_type = winreg.EnumValue(k, i)
                    i += 1

                    if value_name == "MRUListEx":
                        continue

                    if value_type != winreg.REG_BINARY:
                        continue

                    filename = extract_filename(value_data)

                    if not filename:
                        continue

                    item = {
                        "path": full_path,
                        "last_write_time": reg_time_to_string(last_write_time),
                        "value_name": value_name if value_name else "(Default)",
                        "filename": filename
                    }

                    if value_name in mru_index:
                        item["mru_position"] = mru_index[value_name]

                    rows.append(item)

                except OSError:
                    break

            j = 0
            while True:
                try:
                    child = winreg.EnumKey(k, j)
                    j += 1

                    rows.extend(read_recentdocs_tree(
                        root,
                        full_path + "\\" + child,
                        subkey + "\\" + child
                    ))

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
            item.get("filename", "")
        )

        if key in seen:
            continue

        seen.add(key)
        source = item["path"].split("\\RecentDocs", 1)[-1].lstrip("\\")
        result.append({
            "user": user,
            "name": item["filename"],
            "group": source or "all",
            "rank": item.get("mru_position"),
            "key_modified": item["last_write_time"] or None,
        })


for sid in enum_hku():
    add_items(read_recentdocs_tree(
        winreg.HKEY_USERS,
        "HKU\\" + sid + "\\" + RECENTDOCS_KEY,
        sid + "\\" + RECENTDOCS_KEY
    ), sid)


if is_admin():
    loaded_sids = set(enum_hku())

    for hive in find_ntuser_hives():
        mount_name = "_recentdocs_" + str(abs(hash(hive)))

        if mount_name in loaded_sids:
            continue

        if load_hive(hive, mount_name):
            try:
                add_items(read_recentdocs_tree(
                    winreg.HKEY_USERS,
                    "HKU\\" + mount_name + "\\" + RECENTDOCS_KEY,
                    mount_name + "\\" + RECENTDOCS_KEY
                ), Path(hive).parent.name)
            finally:
                unload_hive(mount_name)


result.sort(key=lambda item: (
    item["user"], item["group"],
    item["rank"] if item["rank"] is not None else 999999,
    item["name"]
))

print(json.dumps(result, ensure_ascii=False, indent=2))