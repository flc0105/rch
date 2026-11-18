SCRIPT_METADATA = {
    "name": "mac/shell/shell_history",
    "display_name": "Shell History",
    "description": "List recent commands from zsh/bash history files.",
    "platforms": ["mac"],
    "category": "Shell",
    "params": [
        {
            "name": "limit",
            "label": "Recent commands",
            "type": "number",
            "description": "Number of most recent commands to include.",
            "required": False,
            "default": 50,
        }
    ]
}

import os
import re
from datetime import datetime

from client.runtime.sdk import context



HOME = os.path.expanduser("~")

ZSH_META = re.compile(r"^: (\d+):(\d+);")
BASH_TIMESTAMP = re.compile(r"^#(\d{9,})$")


def _decode_zsh_history(data):
    # zsh escapes certain history bytes as 0x83 followed by (byte ^ 0x20).
    decoded = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0x83 and i + 1 < len(data):
            decoded.append(data[i + 1] ^ 0x20)
            i += 2
        else:
            decoded.append(data[i])
            i += 1
    return decoded.decode("utf-8", errors="replace")


def _parse_zsh(path):
    entries = []
    try:
        with open(path, "rb") as f:
            content = _decode_zsh_history(f.read())
    except Exception as e:
        return {"path": path, "error": str(e), "entries": []}

    buf = []
    ts = None
    for line in content.splitlines():
        m = ZSH_META.match(line)
        if m:
            if buf:
                entries.append({"timestamp": ts, "command": "\n".join(buf)})
            ts = int(m.group(1))
            buf = [line[m.end():]]
        elif buf and buf[-1].endswith("\\"):
            buf.append(line)
        else:
            if buf:
                entries.append({"timestamp": ts, "command": "\n".join(buf)})
            ts = None
            buf = [line] if line.strip() else []

    if buf:
        entries.append({"timestamp": ts, "command": "\n".join(buf)})

    return {"path": path, "entries": entries}


def _parse_bash(path):
    entries = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as e:
        return {"path": path, "error": str(e), "entries": []}

    ts = None
    for line in lines:
        m = BASH_TIMESTAMP.match(line)
        if m:
            ts = int(m.group(1))
            continue
        if line.strip():
            entries.append({"timestamp": ts, "command": line})
            ts = None

    return {"path": path, "entries": entries}


def _format_timestamp(timestamp):
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return None


def _rows(parsed, shell):
    # Entries without timestamps use their position in the history file (last first).
    ordered = sorted(
        enumerate(parsed["entries"]),
        key=lambda item: (
            item[1]["timestamp"] is not None,
            item[1]["timestamp"] or 0,
            item[0],
        ),
        reverse=True,
    )
    return [
        {
            "shell": shell,
            "timestamp": _format_timestamp(entry.get("timestamp")),
            "command": entry["command"],
            "path": parsed["path"],
        }
        for _, entry in ordered
    ]


def main():
    limit = int(kwargs["limit"])
    rows = []

    zsh = os.path.join(HOME, ".zsh_history")
    bash = os.path.join(HOME, ".bash_history")

    if os.path.isfile(zsh):
        rows.extend(_rows(_parse_zsh(zsh), "zsh"))
    if os.path.isfile(bash):
        rows.extend(_rows(_parse_bash(bash), "bash"))

    if limit > 0:
        rows = rows[:limit]
    context.emit(rows)


if __name__ == "__main__":
    main()
