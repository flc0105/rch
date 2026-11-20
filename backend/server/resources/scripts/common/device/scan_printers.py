#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "common/device/scan_printers",
    "display_name": "Printers",
    "description": "List printers set up on this computer and their status.",
    "platforms": ["mac", "win"],
    "category": "Device",
    "params": [],
}

import json
import os
import re
import subprocess

from client.runtime.sdk import context


MAC_PRINTER = re.compile(r"^device for (.+?):\s*(.*)$")
MAC_STATUS = re.compile(r"^printer (\S+) (is idle|now printing|disabled)\b")
MAC_DEFAULT = re.compile(r"^system default destination:\s*(\S+)")


def scan_mac():
    env = dict(os.environ, LC_ALL="C")
    devices = subprocess.run(
        ["lpstat", "-v"], capture_output=True, text=True,
        env=env, timeout=20,
    )
    if devices.returncode != 0:
        message = (devices.stderr or devices.stdout).strip()
        if "No destinations added" in message:
            return []
        raise RuntimeError(message or f"lpstat -v exited with {devices.returncode}")

    printers = {}
    for line in devices.stdout.splitlines():
        match = MAC_PRINTER.match(line)
        if not match:
            continue
        name, uri = match.groups()
        scheme = uri.partition(":")[0].lower() if ":" in uri else None
        printers[name] = {
            "name": name,
            "connection": scheme,
            "port": uri,
            "driver": None,
            "status": None,
            "is_default": False,
        }

    status = subprocess.run(
        ["lpstat", "-p"], capture_output=True, text=True,
        env=env, timeout=20,
    )
    if status.returncode == 0:
        for line in status.stdout.splitlines():
            match = MAC_STATUS.match(line)
            if match and match.group(1) in printers:
                printers[match.group(1)]["status"] = {
                    "is idle": "idle", "now printing": "printing",
                    "disabled": "disabled",
                }[match.group(2)]

    default = subprocess.run(
        ["lpstat", "-d"], capture_output=True, text=True,
        env=env, timeout=20,
    )
    if default.returncode == 0:
        match = MAC_DEFAULT.search(default.stdout)
        if match and match.group(1) in printers:
            printers[match.group(1)]["is_default"] = True

    return sorted(printers.values(), key=lambda item: item["name"].casefold())


def scan_win():
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$default = Get-CimInstance -ClassName Win32_Printer -ErrorAction Stop |
    Where-Object { $_.Default } | Select-Object -First 1 -ExpandProperty Name
$items = @(Get-Printer -ErrorAction Stop | ForEach-Object {
    [PSCustomObject]@{
        name = [string]$_.Name
        connection = [string]$_.Type
        port = [string]$_.PortName
        driver = [string]$_.DriverName
        status = [string]$_.PrinterStatus
        is_default = ($_.Name -eq $default)
    }
})
ConvertTo-Json -InputObject $items -Depth 3 -Compress
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True, timeout=45,
    )
    output = json.loads(result.stdout.lstrip("\ufeff"))
    if output is None:
        return []
    return output if isinstance(output, list) else [output]


def main():
    try:
        os_alias = context.os_alias()
        if os_alias == "mac":
            output = scan_mac()
        elif os_alias == "win":
            output = scan_win()
        else:
            raise RuntimeError(f"Unsupported platform: {os_alias}")
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired,
            subprocess.CalledProcessError, RuntimeError) as exc:
        output = {"error": f"Failed to list printers: {exc}"}

    context.emit(output)


if __name__ == "__main__":
    main()