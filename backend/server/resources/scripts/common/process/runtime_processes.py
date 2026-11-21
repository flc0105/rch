#!/usr/bin/env python3
"""List Python, Node.js or Java processes on Windows, macOS and Linux."""

SCRIPT_METADATA = {
    "name": "common/process/runtime_processes",
    "display_name": "Runtime Processes",
    "description": "Explore running Python, Node.js and Java processes.",
    "category": "process",
    "tags": ["python", "node", "java", "processes"],
    "platforms": ["win", "mac", "linux"],
    "params": [
        {
            "name": "runtime",
            "label": "Runtime",
            "type": "select",
            "required": False,
            "default": "python",
            "options": ["python", "node", "java"],
            "description": "Choose which runtime to inspect.",
        }
    ],
}

import ntpath
import os
import re
import shlex
import subprocess
import time

import psutil
from client.runtime.sdk import context
from client.process.service_lookup import PidServiceLookup


RUNTIME_EXES = {
    "python": re.compile(r"^(?:python(?:w)?(?:\d+(?:\.\d+)*[a-z]*)?|pypy(?:\d+(?:\.\d+)*)?)$", re.I),
    "node": re.compile(r"^node(?:js)?$", re.I),
    "java": re.compile(r"^javaw?$", re.I),
}


def executable_name(value):
    name = ntpath.basename(str(value or "").replace("/", "\\"))
    return name[:-4] if name.lower().endswith(".exe") else name


def matches_runtime(name, exe, argv, runtime):
    return any(
        RUNTIME_EXES[runtime].fullmatch(executable_name(value))
        for value in (name, exe, argv[0] if argv else "")
        if value
    )


def process_value(proc, attribute):
    try:
        return getattr(proc, attribute)()
    except (psutil.Error, OSError, AttributeError):
        return None


def script_info(argv, cwd, os_alias, runtime):
    """Return the launcher entry, its resolved file path and argv position."""
    paths = ntpath if os_alias == "win" else os.path
    i = 1
    java_jar = False
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            i += 1
            break

        if runtime == "python":
            if arg == "-m":
                return (argv[i + 1], None, None) if i + 1 < len(argv) else (None, None, None)
            if arg.startswith("-m") and len(arg) > 2:
                return arg[2:], None, None
            if arg == "-c" or (arg.startswith("-c") and len(arg) > 2):
                return None, None, None
            if arg in ("-X", "-W", "--check-hash-based-pycs"):
                i += 2
                continue

        elif runtime == "node":
            if (arg in ("-e", "--eval", "-p", "--print")
                    or arg.startswith(("--eval=", "--print="))
                    or (len(arg) > 2 and arg[:2] in ("-e", "-p"))):
                return None, None, None
            if arg in ("-r", "--require", "--import", "--loader", "--experimental-loader"):
                i += 2
                continue
            if arg.startswith("-r") and len(arg) > 2:
                i += 1
                continue
            if arg == "--run":
                return (argv[i + 1], None, None) if i + 1 < len(argv) else (None, None, None)

        elif runtime == "java":
            if arg in ("-jar", "-m", "--module"):
                if i + 1 >= len(argv):
                    return None, None, None
                if arg != "-jar":
                    return argv[i + 1], None, None
                java_jar = True
                i += 1
                break
            if arg in ("-cp", "-classpath", "--class-path", "-p", "--module-path",
                       "--upgrade-module-path", "--patch-module", "--source", "--add-opens",
                       "--add-exports", "--add-reads", "--limit-modules"):
                i += 2
                continue
            if arg in ("-version", "--version", "-help", "--help"):
                return None, None, None

        if arg.startswith("-") and arg != "-":
            i += 1
            continue
        break

    if i >= len(argv) or argv[i] == "-":
        return None, None, None
    entry = argv[i]
    if runtime == "java" and not java_jar and not entry.lower().endswith(".java"):
        return entry, None, None  # Java main class
    name = paths.basename(entry) or None
    if paths.isabs(entry):
        return name, paths.normpath(entry), i
    if cwd and paths.isabs(cwd):
        return name, paths.normpath(paths.join(cwd, entry)), i
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
    if value is None:
        return "Unknown"
    return str(getattr(value, "value", value)).replace("-", " ").replace("_", " ").title()


def listening_ports(proc):
    method = getattr(proc, "net_connections", None)
    if not callable(method):
        method = getattr(proc, "connections", None)
    if not callable(method):
        return []
    try:
        connections = method(kind="tcp")
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


def resolved_command(argv, exe, script_path, script_index, os_alias):
    if not argv:
        return ""
    args = list(argv)
    if exe:
        args[0] = exe
    if script_index is not None and script_path:
        args[script_index] = script_path
    return subprocess.list2cmdline(args) if os_alias == "win" else shlex.join(args)


def list_runtime_processes(os_alias, runtime):
    now = time.time()
    service_lookup = PidServiceLookup(os_alias)
    rows = []
    for proc in psutil.process_iter():
        try:
            with proc.oneshot():
                name = process_value(proc, "name")
                exe = process_value(proc, "exe")
                argv = process_value(proc, "cmdline") or []
                if not matches_runtime(name, exe, argv, runtime):
                    continue
                ppid = process_value(proc, "ppid")
                user = process_value(proc, "username")
                created_at = process_value(proc, "create_time")
                status = process_value(proc, "status")
                cwd = process_value(proc, "cwd") if argv else None
            pid = proc.pid
            script_name, script_path, script_index = (
                script_info(argv, cwd, os_alias, runtime) if argv else (None, None, None)
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
                "unit": service_lookup.get(pid),
            })
        except (psutil.Error, OSError):
            continue

    return sorted(rows, key=lambda entry: entry["pid"])


def main():
    os_alias = context.os_alias()
    if os_alias not in ("win", "mac", "linux"):
        raise RuntimeError("Runtime Processes requires a Windows, macOS or Linux client")
    runtime = str((globals().get("kwargs") or {}).get("runtime", "python") or "python").lower()
    if runtime not in RUNTIME_EXES:
        raise ValueError("Runtime must be python, node or java")
    context.emit_view(list_runtime_processes(os_alias, runtime), view={
        'actions': [
            {'label': 'Kill', 'command': 'acmd kill --pid {pid}'},
            {'label': 'Force Kill', 'command': 'acmd kill --pid {pid} -9'},
        ],
    })


if __name__ == "__main__":
    main()