SCRIPT_METADATA = {
    "name": "mac/system/session_interactivity",
    "display_name": "Session Interactivity (macOS)",
    "description": "Check whether the current security session has graphical (Aqua) access.",
    "platforms": ["mac"],
    "category": "System",
    "params": []
}

import ctypes
import json
import subprocess
import sys

if sys.platform != "darwin":
    raise RuntimeError("macOS only")

SESSION_HAS_GRAPHIC_ACCESS = 0x0010


def _session_has_graphic_access():
    try:
        security = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security"
        )
    except OSError:
        return None

    caller = -1  # callerSecuritySession
    attrs = ctypes.c_uint32(0)
    sid = ctypes.c_int32(caller)

    status = security.SessionGetInfo(
        caller, ctypes.byref(sid), ctypes.byref(attrs)
    )
    if status != 0:
        return None
    return bool(attrs.value & SESSION_HAS_GRAPHIC_ACCESS)


def _managername():
    try:
        out = subprocess.run(
            ["launchctl", "managername"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def main():
    result = {
        "platform": "macOS",
        "session_id": None,
        "interactive": False,
        "session_has_graphic_access": None,
        "launchctl_managername": None,
        "reason": None,
    }

    try:
        result["session_id"] = __import__("os").getsid(0)
    except Exception:
        pass

    graphic = _session_has_graphic_access()
    result["session_has_graphic_access"] = graphic
    result["launchctl_managername"] = _managername()

    if graphic is not None:
        result["interactive"] = graphic
        result["reason"] = "SessionGetInfo sessionHasGraphicAccess"
    elif result["launchctl_managername"] is not None:
        result["interactive"] = result["launchctl_managername"] == "Aqua"
        result["reason"] = "launchctl managername heuristic"
    else:
        result["reason"] = "unable to determine"

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()