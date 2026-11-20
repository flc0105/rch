#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "common/device/usb_eject_blockers",
    "display_name": "USB Eject Blockers",
    "description": "Find processes involved in failed USB drive ejections.",
    "platforms": ["mac", "win"],
    "category": "Device",
    "params": [
        {"name": "target", "label": "Device or volume", "type": "string",
         "required": False, "default": "",
         "description": "macOS volume name or path; Windows device ID filter."},
        {"name": "minutes", "label": "Windows event lookback (minutes)",
         "type": "integer", "required": False, "default": 30, "min": 1, "max": 1440},
    ],
}

import json
import ntpath
import os
import subprocess
from datetime import datetime

import psutil
from client.runtime.sdk import context


WINDOWS_EVENTS = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$target = $env:RCH_USB_EJECT_TARGET
$minutes = [int]$env:RCH_USB_EJECT_MINUTES
try {
    $events = @(Get-WinEvent -FilterHashtable @{
        LogName = 'System'
        ProviderName = 'Microsoft-Windows-Kernel-PnP'
        Id = 225
        StartTime = (Get-Date).AddMinutes(-$minutes)
    } -MaxEvents 300 -ErrorAction Stop)
} catch {
    if ($_.FullyQualifiedErrorId -match 'NoMatchingEventsFound') {
        $events = @()
    } else {
        throw
    }
}
$rows = @(
    foreach ($entry in $events) {
        [xml]$xml = $entry.ToXml()
        $fields = @{}
        foreach ($field in @($xml.Event.EventData.Data)) {
            if ($null -ne $field) {
                $key = $field.GetAttribute('Name')
                if ($key) { $fields[$key] = $field.InnerText }
            }
        }
        $device = [string]$fields['DeviceInstance']
        $affected = [string]$fields['VetoingDevices']
        if ($target -and
            $device.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -lt 0 -and
            $affected.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            continue
        }
        [PSCustomObject]@{
            time = $entry.TimeCreated.ToString('o')
            pid = [string]$fields['ProcessId']
            reported_image = [string]$fields['ProcessName']
            device_instance = $device
            affected_devices = $affected
        }
    }
)
ConvertTo-Json -InputObject $rows -Depth 3 -Compress
'''


def process_details(pid, event_time=None, live=False):
    """Only enrich an old event if the same PID existed when it occurred."""
    try:
        proc = psutil.Process(pid)
        if event_time is not None and proc.create_time() > event_time + 1:
            return {"still_running": False}
        if event_time is None and not live:
            return {"still_running": None}
        details = {"still_running": True}
        for field, getter in (("process_name", proc.name),
                              ("process_path", proc.exe),
                              ("user", proc.username)):
            try:
                details[field] = getter()
            except (psutil.Error, OSError):
                pass
        return details
    except psutil.NoSuchProcess:
        return {"still_running": False}
    except (psutil.Error, OSError):
        return {"still_running": None}


def scan_win(target, minutes):
    env = dict(os.environ, RCH_USB_EJECT_TARGET=target, RCH_USB_EJECT_MINUTES=str(minutes))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_EVENTS],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=60, check=True,
    )
    records = json.loads(result.stdout.lstrip("\ufeff"))
    if not isinstance(records, list):
        raise ValueError("Unexpected Windows event response")
    processes = []
    for record in records:
        if not isinstance(record, dict):
            continue
        raw_pid = str(record.get("pid") or "")
        pid = int(raw_pid) if raw_pid.isdecimal() else None
        image = str(record.get("reported_image") or "")
        entry = {
            "pid": pid,
            "process_name": ntpath.basename(image) or None,
            "reported_image": image or None,
            "device_instance": record.get("device_instance") or None,
            "time": record.get("time") or None,
            "source": "Kernel-PnP/225",
        }
        if record.get("affected_devices"):
            entry["affected_devices"] = record["affected_devices"]
        if pid is not None:
            try:
                observed = datetime.fromisoformat(entry["time"]).timestamp()
            except (TypeError, ValueError, OverflowError):
                observed = None
            details = process_details(pid, observed)
            entry.update(details)
            if not entry["process_name"]:
                entry["process_name"] = details.get("process_name")
        processes.append(entry)
    return {
        "source": "Kernel-PnP/225", "scope": "recent_eject_failures",
        "target": target or None, "lookback_minutes": minutes,
        "count": len(processes), "processes": processes,
    }


def parse_lsof(text):
    rows = {}
    current = None
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
            current = rows.setdefault(pid, {
                "pid": pid, "process_name": None, "open_files": [],
            })
        elif current is not None and line.startswith("c"):
            current["process_name"] = line[1:] or None
        elif current is not None and line.startswith("n"):
            path = line[1:]
            if path and path not in current["open_files"]:
                current["open_files"].append(path)
    return sorted(rows.values(), key=lambda entry: entry["pid"])


def scan_mac(target):
    if not target:
        raise ValueError("Provide a mounted USB volume name or /Volumes/path")
    volume = target if target.startswith("/") else os.path.join("/Volumes", target)
    volume = os.path.normpath(volume)
    if not volume.startswith("/Volumes/") or not os.path.ismount(volume):
        raise ValueError(f"Not a mounted volume under /Volumes: {volume}")
    result = subprocess.run(
        ["lsof", "-nP", "-Fpcn", "+f", "--", volume],
        capture_output=True, text=True, errors="replace", timeout=60,
    )
    if result.returncode not in (0, 1) or (not result.stdout and result.stderr.strip()):
        raise RuntimeError(result.stderr.strip() or f"lsof exit code {result.returncode}")
    processes = parse_lsof(result.stdout)
    for entry in processes:
        details = process_details(entry["pid"], live=True)
        # lsof is a live query; unlike a historical event, these are current PIDs.
        details.pop("still_running", None)
        for key in ("process_path", "user"):
            if details.get(key):
                entry[key] = details[key]
    output = {
        "source": "lsof", "scope": "current_open_files",
        "target": volume, "count": len(processes), "processes": processes,
    }
    if result.stderr.strip():
        output["warning"] = result.stderr.strip()
    return output


def main():
    try:
        params = globals().get("kwargs") or {}
        target = str(params.get("target") or "").strip()
        minutes = int(params.get("minutes", 30))
        if not 1 <= minutes <= 1440:
            raise ValueError("minutes must be between 1 and 1440")
        os_alias = context.os_alias()
        if os_alias == "win":
            output = scan_win(target, minutes)
        elif os_alias == "mac":
            output = scan_mac(target)
        else:
            raise RuntimeError(f"Unsupported platform: {os_alias}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        output = {"error": f"Failed to inspect USB eject blockers: {exc}"}
    context.emit(output)


if __name__ == "__main__":
    main()