"""Shared macOS command utilities."""


def escape_osascript_text(value: str) -> str:
    text = str(value or '')
    text = text.replace('\\', '\\\\')
    text = text.replace('"', '\\"')
    return text
