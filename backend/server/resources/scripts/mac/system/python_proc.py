#!/usr/bin/env python3
"""Print running macOS Python processes as a flat JSON array. Standard library only."""

import ctypes
import ctypes.util
import json
import os
import pwd
import re
import shlex
import subprocess
import sys


PYTHON_EXE = re.compile(r"^(?:python(?:w)?(?:\d+(?:\.\d+)*[a-z]*)?|pypy(?:\d+(?:\.\d+)*)?)$", re.I)
PROCESS_LINE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(.*)$")


def run_command(args, timeout=15):
    return subprocess.run(
        args, capture_output=True, text=True, errors="replace", timeout=timeout,
        check=False,
    )


def process_names():
    """Map PID to the actual process name reported by ps (comm)."""
    result = run_command(["ps", "-axww", "-o", "pid=", "-o", "comm="])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ps failed")
    names = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            names[int(parts[0])] = os.path.basename(parts[1])
    return names


def is_python_executable(value):
    return bool(PYTHON_EXE.fullmatch(os.path.basename(value)))


def real_argv(pid):
    """Read NUL-separated argv through the macOS KERN_PROCARGS2 API.

    Unlike `ps command`, this preserves spaces inside individual path arguments.
    Permission restrictions can make this unavailable for some processes.
    """
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib", use_errno=True)
        sysctl = libc.sysctl
        sysctl.argtypes = [
            ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p, ctypes.c_size_t,
        ]
        sysctl.restype = ctypes.c_int
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2, PID
        size = ctypes.c_size_t()
        if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            return None
        if not 4 < size.value <= 8 * 1024 * 1024:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
            return None
        raw = buf.raw[:size.value]
        count = int.from_bytes(raw[:4], sys.byteorder, signed=True)
        if count < 1 or count > 65536:
            return None
        payload = raw[4:]
        exe_end = payload.find(b"\x00")
        if exe_end < 0:
            return None
        payload = payload[exe_end + 1:].lstrip(b"\x00")
        argv = []
        for _ in range(count):
            end = payload.find(b"\x00")
            if end < 0:
                return None
            argv.append(os.fsdecode(payload[:end]))
            payload = payload[end + 1:]
        return argv
    except (OSError, ValueError, AttributeError, OverflowError):
        return None


def fallback_argv(command):
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def working_directory(pid):
    """Retrieve current CWD, only when a relative script needs resolution."""
    try:
        result = run_command(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("n") and os.path.isabs(line[1:]):
            return line[1:]
    return None


def script_info(argv, pid):
    """Extract a script name and absolute path, when available.

    `python -m MODULE`, `python -c CODE`, and interactive Python have no
    ordinary script filename in argv, so script_path is null.
    """
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            i += 1
            break
        if arg == "-m":
            return (argv[i + 1], None) if i + 1 < len(argv) else (None, None)
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:], None
        if arg == "-c" or (arg.startswith("-c") and len(arg) > 2):
            return None, None
        if arg in ("-X", "-W"):
            i += 2
            continue
        if arg.startswith("-") and arg != "-":
            i += 1
            continue
        break

    if i >= len(argv) or argv[i] == "-":
        return None, None
    script = argv[i]
    name = os.path.basename(script) or None
    if os.path.isabs(script):
        return name, os.path.normpath(script)
    cwd = working_directory(pid)
    return name, os.path.abspath(os.path.join(cwd, script)) if cwd else None


def format_elapsed(elapsed):
    """Convert ps etime ([days-]hours:minutes:seconds) to readable duration."""
    try:
        days = 0
        if "-" in elapsed:
            day_text, elapsed = elapsed.split("-", 1)
            days = int(day_text)
        parts = [int(part) for part in elapsed.split(":")]
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours, (minutes, seconds) = 0, parts
        elif len(parts) == 1:
            hours, minutes, seconds = 0, 0, parts[0]
        else:
            return None
        return (f"{days}d " if days else "") + f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except ValueError:
        return None


def listening_ports_by_pid():
    """Return each visible PID's TCP LISTEN ports, using macOS's built-in lsof.

    Runs lsof only once. Socket connections that are not listening are excluded.
    Some other users' processes may require sudo to inspect.
    """
    try:
        result = run_command(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"], timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    ports = {}
    pid = None
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            # Examples: n*:8080, n127.0.0.1:8000, n[::1]:5000
            suffix = line[1:].rsplit(":", 1)[-1]
            if suffix.isdigit():
                port = int(suffix)
                if 0 < port <= 65535:
                    ports.setdefault(pid, set()).add(port)
    return {pid: sorted(values) for pid, values in ports.items()}


def main():
    if sys.platform != "darwin":
        print("This script is intended for macOS.", file=sys.stderr)
        return 1

    names = process_names()
    listening_ports = listening_ports_by_pid()
    result = run_command(["ps", "-axww", "-o", "pid=", "-o", "uid=", "-o", "etime=", "-o", "command="])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ps failed")

    output = []
    for line in result.stdout.splitlines():
        match = PROCESS_LINE.match(line)
        if not match:
            continue
        pid = int(match.group(1))
        user_id = match.group(2)
        try:
            user = pwd.getpwuid(int(user_id)).pw_name
        except (KeyError, ValueError):
            user = user_id
        elapsed = match.group(3)
        ps_command = match.group(4)
        name = names.get(pid)
        tentative = fallback_argv(ps_command)
        if not tentative:
            continue
        if not (is_python_executable(name or "") or is_python_executable(tentative[0])):
            continue

        argv = real_argv(pid) or tentative
        if not argv:
            continue
        script_name, script_path = script_info(argv, pid)
        output.append({
            "script_name": script_name,
            "script_path": script_path,
            "process_name": name or os.path.basename(argv[0]),
            "pid": pid,
            "running_time": format_elapsed(elapsed),
            "user": user,
            "command": shlex.join(argv),
            "listening_ports": listening_ports.get(pid, []),
        })

    output.sort(key=lambda entry: entry["pid"])
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()