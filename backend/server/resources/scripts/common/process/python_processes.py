#!/usr/bin/env python3
"""List running Python processes on Windows, macOS and Linux as a JSON array."""

SCRIPT_METADATA = {
    "name": "common/process/python_processes",
    "display_name": "Python Processes",
    "description": "List running Python processes.",
    "category": "process",
    "tags": ["python", "processes"],
    "platforms": ["win", "mac", "linux"],
    "params": [],
}

import json
import ntpath
import os
import re
import shlex
import subprocess
import time

import psutil
from client.runtime.sdk import context


PYTHON_EXE = re.compile(
    r"^(?:python(?:w)?(?:\d+(?:\.\d+)*[a-z]*)?|pypy(?:\d+(?:\.\d+)*)?)$",
    re.I,
)


def executable_name(value):
    """Recognize Windows .exe and Unix executable paths consistently."""
    name = ntpath.basename(str(value or "").replace("/", "\\"))
    return name[:-4] if name.lower().endswith(".exe") else name


def is_python_executable(value):
    return bool(PYTHON_EXE.fullmatch(executable_name(value)))


def process_value(proc, attribute):
    try:
        return getattr(proc, attribute)()
    except (psutil.Error, OSError):
        return None


def script_info(argv, cwd, os_alias):
    """Extract a script or -m module without losing spaces in argv."""
    paths = ntpath if os_alias == "win" else os.path
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            i += 1
            break
        if arg == "-m":
            return (argv[i + 1], None, None) if i + 1 < len(argv) else (None, None, None)
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:], None, None
        if arg == "-c" or (arg.startswith("-c") and len(arg) > 2):
            return None, None, None
        if arg in ("-X", "-W", "--check-hash-based-pycs"):
            i += 2
            continue
        if arg.startswith("-") and arg != "-":
            i += 1
            continue
        break

    if i >= len(argv) or argv[i] == "-":
        return None, None, None
    script = argv[i]
    name = paths.basename(script) or None
    if paths.isabs(script):
        return name, paths.normpath(script), i
    if cwd and paths.isabs(cwd):
        return name, paths.normpath(paths.join(cwd, script)), i
    return name, None, i


def format_elapsed(created_at, now):
    if created_at is None:
        return None
    try:
        seconds = max(0, int(now - float(created_at)))
    except (TypeError, ValueError, OverflowError):
        return None
    hours, remain = divmod(seconds, 3600)
    minutes, seconds = divmod(remain, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_status(value):
    """Keep psutil statuses readable across string and enum-based versions."""
    if value is None:
        return "Unknown"
    return str(getattr(value, "value", value)).replace("-", " ").replace("_", " ").title()


def listening_ports(proc):
    """Only include the process's TCP listening sockets; unavailable ports stay empty."""
    # psutil 6+ uses net_connections; older installations use connections.
    connection_method = getattr(proc, "net_connections", None)
    if not callable(connection_method):
        connection_method = getattr(proc, "connections", None)
    if not callable(connection_method):
        return []
    try:
        connections = connection_method(kind="tcp")
    except (psutil.Error, OSError, NotImplementedError):
        return []
    ports = set()
    for conn in connections:
        if conn.status != psutil.CONN_LISTEN or not conn.laddr:
            continue
        port = getattr(conn.laddr, "port", None)
        if port is not None and 0 < int(port) <= 65535:
            ports.add(int(port))
    return sorted(ports)


def format_command(argv, os_alias):
    if not argv:
        return ""
    if os_alias == "win":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def resolved_command(argv, exe, script_path, script_index, os_alias):
    """Display the executable and script with absolute paths when available."""
    if not argv:
        return ""
    args = list(argv)
    if exe:
        args[0] = exe
    if script_index is not None and script_path:
        args[script_index] = script_path
    return format_command(args, os_alias)


def list_python_processes(os_alias):
    now = time.time()
    rows = []
    for proc in psutil.process_iter():
        try:
            with proc.oneshot():
                name = process_value(proc, "name")
                exe = process_value(proc, "exe")
                argv = process_value(proc, "cmdline") or []
                if not any(is_python_executable(value) for value in
                           (name, exe, argv[0] if argv else "")):
                    continue
                ppid = process_value(proc, "ppid")
                user = process_value(proc, "username")
                created_at = process_value(proc, "create_time")
                status = process_value(proc, "status")
                cwd = process_value(proc, "cwd") if argv else None

            pid = proc.pid
            script_name, script_path, script_index = (
                script_info(argv, cwd, os_alias) if argv else (None, None, None)
            )
            rows.append({
                "script_name": script_name,
                "script_path": script_path,
                "process_name": name or executable_name(exe or (argv[0] if argv else "")),
                "pid": pid,
                "ppid": ppid,
                "status": format_status(status),
                "running_time": format_elapsed(created_at, now),
                "user": user,
                "command": resolved_command(argv, exe, script_path, script_index, os_alias) or str(name or ""),
                "listening_ports": listening_ports(proc),
                "_actions": [
                    {"label": "Kill", "command": f"acmd kill --pid {pid}"},
                    {"label": "Force Kill", "command": f"acmd kill --pid {pid} -9"},
                ],
            })
        except (psutil.Error, OSError):
            # Processes may exit or become inaccessible while being enumerated.
            continue

    return sorted(rows, key=lambda entry: entry["pid"])


def main():
    os_alias = context.os_alias()
    if os_alias not in ("win", "mac", "linux"):
        raise RuntimeError("Python Processes requires a Windows, macOS or Linux client")
    print(json.dumps(list_python_processes(os_alias), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()