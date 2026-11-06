SCRIPT_METADATA = {
    "name": "mac/defense/tcc_permissions",
    "display_name": "TCC Permissions (macOS)",
    "description": "Enumerate TCC privacy permissions (camera, mic, screen capture, accessibility, FDA) from TCC.db.",
    "platforms": ["mac"],
    "category": "Defense",
    "params": []
}

import json
import os
import sqlite3
import sys

if sys.platform != "darwin":
    raise RuntimeError("macOS only")

HOME = os.path.expanduser("~")

TCC_DBS = [
    {
        "scope": "user",
        "path": os.path.join(
            HOME, "Library", "Application Support", "com.apple.TCC", "TCC.db"
        ),
    },
    {
        "scope": "system",
        "path": "/Library/Application Support/com.apple.TCC/TCC.db",
    },
]

AUTH_VALUE = {
    0: "denied",
    1: "unknown",
    2: "allowed",
    3: "limited",
}

SERVICE_HINTS = {
    "kTCCServiceCamera": "camera",
    "kTCCServiceMicrophone": "microphone",
    "kTCCServiceScreenCapture": "screen_capture",
    "kTCCServiceAccessibility": "accessibility",
    "kTCCServiceSystemPolicyAllFiles": "full_disk_access",
    "kTCCServiceSystemPolicyDesktopFolder": "desktop_folder",
    "kTCCServiceSystemPolicyDocumentsFolder": "documents_folder",
    "kTCCServiceSystemPolicyDownloadsFolder": "downloads_folder",
}


def _read_tcc_db(entry):
    path = entry["path"]
    result = {
        "scope": entry["scope"],
        "path": path,
        "exists": os.path.exists(path),
        "readable": False,
        "entries": [],
        "error": None,
    }

    if not result["exists"]:
        return result

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        if "access" not in tables:
            result["error"] = "no 'access' table in TCC.db"
            conn.close()
            return result

        cur.execute("SELECT * FROM access")
        for row in cur.fetchall():
            d = dict(row)
            service = d.get("service")
            entry = {
                "service": service,
                "service_hint": SERVICE_HINTS.get(service),
                "client": d.get("client"),
                "client_type": d.get("client_type"),
                "auth_value": d.get("auth_value"),
                "auth_meaning": AUTH_VALUE.get(d.get("auth_value")),
                "last_modified": d.get("last_modified"),
            }
            result["entries"].append(entry)

        conn.close()
        result["readable"] = True

    except sqlite3.OperationalError as e:
        result["error"] = f"sqlite open failed: {e}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def main():
    result = {
        "platform": "macOS",
        "databases": [],
        "notes": [],
    }

    for entry in TCC_DBS:
        result["databases"].append(_read_tcc_db(entry))

    if not any(db["readable"] for db in result["databases"]):
        result["notes"].append(
            "No TCC.db could be read. Full Disk Access (or TCC authorization "
            "for the calling process) is required."
        )

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()