import json
import os
from typing import Any


def read_json_file(path: Any) -> dict:
    with open(str(path or ''), 'r', encoding='utf-8') as file_obj:
        data = json.load(file_obj)
    return data if isinstance(data, dict) else {}


def read_json_file_or_empty(path: Any) -> dict:
    try:
        return read_json_file(path)
    except Exception:
        return {}


def write_json_file(path: Any, data: dict):
    target = str(path or '')
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as file_obj:
        json.dump(data if isinstance(data, dict) else {}, file_obj, ensure_ascii=False, indent=2)


def tail_text_file(path: Any, max_bytes: int) -> str:
    target = str(path or '')
    if not os.path.isfile(target):
        return ''
    with open(target, 'rb') as file_obj:
        if max_bytes > 0:
            file_obj.seek(0, os.SEEK_END)
            size = file_obj.tell()
            file_obj.seek(max(0, size - max_bytes), os.SEEK_SET)
        raw = file_obj.read()
    return raw.decode('utf-8', errors='replace')
