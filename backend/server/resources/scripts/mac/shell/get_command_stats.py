
#!/usr/bin/env python3
SCRIPT_METADATA = {
    "name": "mac/shell/get_command_stats",
    "display_name": "Command Stats",
    "description": "Show the most frequently used commands in zsh history.",
    "platforms": ["mac"],
    "category": "Shell",
    "params": [
        {
            "name": "limit",
            "type": "number",
            "required": False,
            "default": 20,
            "description": "Maximum number of commands to return."
        }
    ]
}

import json
import re
import shlex
from pathlib import Path
from collections import Counter

HISTORY_PATH = Path.home() / ".zsh_history"
HISTORY_HEADER = re.compile(r"^: \d+:\d+;")

SKIP_COMMANDS = {
    "command-stats",
    "\\", "|", "||", "&&", ";",
    "if", "then", "else", "elif", "fi",
    "for", "while", "until", "do", "done",
    "case", "esac", "function",
    "{", "}", "(", ")",
}


def read_history():
    if not HISTORY_PATH.is_file():
        raise FileNotFoundError("Zsh history file not found.")

    entries = []
    current = None
    pending = []

    with HISTORY_PATH.open(
        encoding="utf-8",
        errors="replace"
    ) as history:
        for line in history:
            line = line.rstrip("\r\n")
            match = HISTORY_HEADER.match(line)

            if match:
                if current is not None:
                    entries.append("\n".join(current))

                current = [line[match.end():]]
                continue

            if current is not None:
                current.append(line)
                continue

            if not line.strip() and not pending:
                continue

            pending.append(line)

            if not line.rstrip().endswith("\\"):
                entries.append("\n".join(pending))
                pending = []

    if current is not None:
        entries.append("\n".join(current))

    if pending:
        entries.append("\n".join(pending))

    return entries


def get_command(entry):
    entry = re.sub(r"\\\r?\n\s*", " ", entry).strip()

    if not entry:
        return None

    try:
        parts = shlex.split(entry)
    except ValueError:
        return None

    if not parts:
        return None

    command = parts[0]

    if command in SKIP_COMMANDS:
        return None

    if command == "sudo":
        index = 1
        options_with_value = {
            "-u", "-g", "-p", "-C",
            "--user", "--group", "--prompt"
        }

        while index < len(parts):
            option = parts[index]

            if option == "--":
                index += 1
                break

            if option in options_with_value:
                index += 2
            elif option.startswith("-"):
                index += 1
            else:
                break

        if index >= len(parts):
            return None

        command = parts[index]

    command = Path(command).name

    if not command or command in SKIP_COMMANDS:
        return None

    return command


def main():
    try:
        limit = int(kwargs.get("limit", 20))

        if limit <= 0:
            raise ValueError("Limit must be greater than zero.")

        commands = []

        for entry in read_history():
            command = get_command(entry)
            if command:
                commands.append(command)

        counts = Counter(commands)

        output = [
            {"command": command, "count": count}
            for command, count in counts.most_common(limit)
        ]

    except (OSError, ValueError, TypeError) as exc:
        output = {"error": str(exc)}

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()