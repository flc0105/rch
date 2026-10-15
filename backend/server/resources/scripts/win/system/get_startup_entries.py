SCRIPT_METADATA = {
    "name": "win/system/get_startup_entries",
    "display_name": "Startup Entries",
    "description": "List startup commands configured in the Windows registry.",
    "platforms": ["win"],
    "category": "System",
    "params": []
}

import os
import json
import glob
import ctypes
import subprocess
from pathlib import Path

try:
    import winreg
except ImportError:
    print('{"error": "Windows platform support is required."}')
    raise SystemExit(1)


RUN_KEYS = [
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
]

HKLM_KEYS = [
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce",
]


def normalize_value(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def read_key(root, full_path, subkey):
    rows = []

    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                    rows.append({
                        "source": full_path,
                        "name": name if name else "(Default)",
                        "command": normalize_value(value)
                    })
                    i += 1
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

for key in HKLM_KEYS:
    result.extend(read_key(
        winreg.HKEY_LOCAL_MACHINE,
        "HKLM\\" + key,
        key
    ))

for sid in enum_hku():
    for key in RUN_KEYS:
        result.extend(read_key(
            winreg.HKEY_USERS,
            "HKU\\" + sid + "\\" + key,
            sid + "\\" + key
        ))

if is_admin():
    loaded = set(enum_hku())

    for hive in find_ntuser_hives():
        mount_name = "_forensic_" + str(abs(hash(hive)))

        if mount_name in loaded:
            continue

        if load_hive(hive, mount_name):
            try:
                for key in RUN_KEYS:
                    result.extend(read_key(
                        winreg.HKEY_USERS,
                        "HKU\\" + mount_name + "\\" + key,
                        mount_name + "\\" + key
                    ))
            finally:
                unload_hive(mount_name)

print(json.dumps(result, ensure_ascii=False, indent=2))