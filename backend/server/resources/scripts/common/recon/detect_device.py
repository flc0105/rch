"""Best-effort form-factor and virtualization detection across major platforms.

Requires only the Python standard library. Python 3.13+ improves Android/iOS support.
`unknown` is deliberate: firmware and VM/container environments may hide details.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path


CHASSIS_TYPES = {
    3: "desktop", 4: "desktop", 5: "desktop", 6: "desktop",
    7: "desktop", 13: "desktop", 15: "desktop",
    9: "laptop", 10: "laptop", 14: "laptop",
    11: "handheld", 23: "server", 28: "server", 29: "server",
    30: "tablet", 31: "convertible", 32: "tablet",
}
VM_HINTS = (
    "vmware", "virtualbox", "virtual machine", "kvm", "qemu",
    "parallels", "bhyve", "xen hvm", "bochs",
)


def run(*command, timeout=8):
    try:
        return subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, UnicodeError):
        return ""


def chassis_type(codes):
    for code in codes:
        try:
            name = CHASSIS_TYPES.get(int(code))
        except (ValueError, TypeError):
            continue
        if name:
            return name
    return "unknown"


def detect_device():
    system = platform.system()
    result = {
        "os": system,
        "device_type": "unknown",
        "virtualization": "unknown",
        "model": "",
        "source": "unknown",
    }

    # iOS / iPadOS: Python 3.13+ official APIs.
    if system in ("iOS", "iPadOS") or sys.platform == "ios":
        result["os"] = system if system in ("iOS", "iPadOS") else "iOS"
        result["device_type"] = "tablet" if system == "iPadOS" else "phone"
        result["source"] = "platform.ios_ver"
        if hasattr(platform, "ios_ver"):
            info = platform.ios_ver()
            result["model"] = info.model
            if info.model.lower().startswith("ipad"):
                result["device_type"] = "tablet"
            elif info.model.lower().startswith("iphone"):
                result["device_type"] = "phone"
            if info.is_simulator:
                result["virtualization"] = "simulator"
        return result

    # Android can appear as Linux on older, unofficial Python builds.
    android = (
        system == "Android" or sys.platform == "android"
        or hasattr(sys, "getandroidapilevel")
        or ("ANDROID_ROOT" in os.environ and "ANDROID_DATA" in os.environ)
    )
    if android:
        result["os"] = "Android"
        result["device_type"] = "mobile"  # Phone vs tablet cannot always be established.
        result["source"] = "Android properties"
        if hasattr(platform, "android_ver"):
            try:
                info = platform.android_ver()
                result["model"] = info.model
                if info.is_emulator:
                    result["virtualization"] = "emulator"
            except (OSError, RuntimeError, AttributeError):
                pass
        prop_tool = "/system/bin/getprop" if Path("/system/bin/getprop").exists() else "getprop"
        chars = run(prop_tool, "ro.build.characteristics").lower().split(",")
        if "tablet" in chars:
            result["device_type"] = "tablet"
        elif "phone" in chars:
            result["device_type"] = "phone"
        if not result["model"]:
            result["model"] = run(prop_tool, "ro.product.model")
        if run(prop_tool, "ro.kernel.qemu") == "1":
            result["virtualization"] = "emulator"
        return result

    if system == "Windows":
        script = (
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            "$c=Get-CimInstance Win32_SystemEnclosure;"
            "$m=Get-CimInstance Win32_ComputerSystem;"
            "[pscustomobject]@{chassis=@($c.ChassisTypes);"
            "manufacturer=$m.Manufacturer;model=$m.Model} "
            "| ConvertTo-Json -Compress"
        )
        raw = run("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, timeout=12)
        try:
            data = json.loads(raw)
            result["device_type"] = chassis_type(data.get("chassis") or [])
            result["model"] = str(data.get("model") or "")
            result["source"] = "Win32_SystemEnclosure"
            marker = f'{data.get("manufacturer") or ""} {result["model"]}'.lower()
            if any(hint in marker for hint in VM_HINTS):
                result["virtualization"] = "vm"
        except (ValueError, TypeError, AttributeError):
            pass

    elif system == "Darwin":  # macOS (not iOS)
        raw = run("system_profiler", "SPHardwareDataType", "-json", timeout=15)
        try:
            data = json.loads(raw)["SPHardwareDataType"][0]
        except (ValueError, TypeError, KeyError, IndexError):
            data = {}
        name = str(data.get("machine_name") or "")
        model_id = run("sysctl", "-n", "hw.model")
        result["model"] = name or model_id
        result["source"] = "system_profiler / sysctl"
        value = (name or model_id).lower()
        if "macbook" in value:
            result["device_type"] = "laptop"
        elif any(t in value for t in ("imac", "mac mini", "macmini", "mac studio", "macstudio", "mac pro", "macpro")):
            result["device_type"] = "desktop"
        if any(hint in (name + " " + model_id).lower() for hint in VM_HINTS):
            result["virtualization"] = "vm"

    elif system == "Linux":
        code = read("/sys/class/dmi/id/chassis_type")
        result["device_type"] = chassis_type([code])
        result["model"] = read("/sys/class/dmi/id/product_name")
        result["source"] = "Linux DMI / systemd-detect-virt"

        # Query container and VM separately; containers can run inside VMs.
        is_container = bool(run("systemd-detect-virt", "--container"))
        is_vm = bool(run("systemd-detect-virt", "--vm"))
        if is_container or Path("/.dockerenv").exists():
            result["virtualization"] = "container"
        elif is_vm:
            result["virtualization"] = "vm"
        else:
            marker = " ".join((
                read("/sys/class/dmi/id/sys_vendor"), result["model"]
            )).lower()
            if any(hint in marker for hint in VM_HINTS):
                result["virtualization"] = "vm"

    return result


if __name__ == "__main__":
    print(json.dumps(detect_device(), ensure_ascii=False, indent=2))
