import os


def safe_file_size(path: str) -> int:
    try:
        return int(os.path.getsize(path)) if path and os.path.isfile(path) else 0
    except Exception:
        return 0
