SCRIPT_METADATA = {
    "name": "win/defense/defender_exclusion_paths",
    "display_name": "Defender Exclusion Paths",
    "description": "Enumerate Windows Defender path exclusions from registry.",
    "platforms": ["win"],
    "category": "Defense",
    "params": []
}

import json
import sys

if sys.platform != "win32":
    raise RuntimeError("Windows only")

import winreg


DEFENDER_EXCLUSIONS = r"SOFTWARE\Microsoft\Windows Defender\Exclusions\Paths"


def enum_exclusion_paths():
    result = {"key": DEFENDER_EXCLUSIONS, "paths": [], "errors": []}

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            DEFENDER_EXCLUSIONS,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                    result["paths"].append({"path": name, "value": value})
                    index += 1
                except OSError:
                    break
    except FileNotFoundError:
        result["errors"].append("Defender exclusions key not found (Defender may be disabled or removed).")
    except PermissionError:
        result["errors"].append("Access denied. Elevated context required to read HKLM Defender exclusions.")
    except Exception as e:
        result["errors"].append(f"{type(e).__name__}: {e}")

    return result


def main():
    try:
        print(json.dumps(enum_exclusion_paths(), ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    main()