import re


def secure_filename(filename: str) -> str:
    illegal_chars = r'[\\/:\*\?"<>|]'
    return re.sub(illegal_chars, '_', filename)
