SCRIPT_METADATA = {
    "name": "mac/credentials/shell_history",
    "display_name": "Shell History (macOS)",
    "description": "Parse zsh/bash shell history files and summarize commands.",
    "platforms": ["mac"],
    "category": "Credentials",
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

import json
import os
import re
import sys
from datetime import datetime, timezone

if sys.platform != "darwin":
    raise RuntimeError("macOS only")

HOME = os.path.expanduser("~")

ZSH_META = re.compile(r"^: (\d+):(\d+);")
BASH_TIMESTAMP = re.compile(r"^#(\d{9,})$")


def _parse_zsh(path):
    entries = []
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return {"path": path, "error": str(e), "entries": []}

    buf = []
    ts = None
    for line in content.splitlines():
        m = ZSH_META.match(line)
        if m:
            if buf:
                entries.append({"timestamp": ts, "command": "\n".join(buf)})
                buf = []
            ts = int(m.group(1))
            buf.append(line[m.end():])
        else:
            if buf:
                buf.append(line)
            else:
                if line.strip():
                    entries.append({"timestamp": None, "command": line})

    if buf:
        entries.append({"timestamp": ts, "command": "\n".join(buf)})

    for e in entries:
        if e.get("timestamp"):
            try:
                e["time"] = datetime.fromtimestamp(
                    e["timestamp"], tz=timezone.utc
                ).isoformat()
            except Exception:
                pass

    return {"path": path, "entries": entries}


def _parse_bash(path):
    entries = []
    try:
        with open(path, "r", errors="replace") as f:
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


def _summarize(parsed, limit):
    entries = parsed.get("entries", [])
    total = len(entries)
    recent = entries[-limit:] if limit > 0 else entries
    timestamps = [e["timestamp"] for e in entries if e.get("timestamp")]
    return {
        "path": parsed["path"],
        "exists": os.path.isfile(parsed["path"]),
        "error": parsed.get("error"),
        "total_entries": total,
        "earliest": (
            datetime.fromtimestamp(min(timestamps), tz=timezone.utc).isoformat()
            if timestamps else None
        ),
        "latest": (
            datetime.fromtimestamp(max(timestamps), tz=timezone.utc).isoformat()
            if timestamps else None
        ),
        "recent": [
            {"command": e["command"], "timestamp": e.get("timestamp")}
            for e in recent
        ],
    }


def main():
    try:
        limit = int(kwargs.get("limit", 50))
    except Exception:
        limit = 50

    result = {
        "platform": "macOS",
        "histories": [],
    }

    zsh = os.path.join(HOME, ".zsh_history")
    bash = os.path.join(HOME, ".bash_history")

    if os.path.isfile(zsh):
        result["histories"].append(
            _summarize(_parse_zsh(zsh), limit)
        )
    if os.path.isfile(bash):
        result["histories"].append(
            _summarize(_parse_bash(bash), limit)
        )

    if not result["histories"]:
        result["note"] = "No .zsh_history or .bash_history found."

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()