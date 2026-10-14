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


def read_text_log_chunk(path: Any, max_bytes: int, cursor: str | None = None) -> dict:
    """Read a bounded log tail or only bytes added after an opaque cursor.

    Cursor identity detects replacements/rotation; a shortened file restarts at its
    tail. Both initial snapshots and incremental responses include the next cursor.
    """
    target = str(path or '')
    limit = max(1, min(int(max_bytes), 256 * 1024))
    if not os.path.isfile(target):
        return {'content': '', 'cursor': '', 'reset': bool(cursor)}

    with open(target, 'rb') as file_obj:
        stat = os.fstat(file_obj.fileno())
        identity = f'{stat.st_dev:x}:{stat.st_ino:x}'
        length = stat.st_size
        previous_offset = None
        previous_identity = ''
        if cursor:
            try:
                previous_identity, encoded = str(cursor).rsplit(':', 1)
                previous_offset = int(encoded, 16)
            except (ValueError, TypeError):
                previous_offset = None
        continued = previous_offset is not None and previous_identity == identity and 0 <= previous_offset <= length
        reset = bool(cursor) and not continued
        start = previous_offset if continued else max(0, length - limit)
        file_obj.seek(start)
        raw = file_obj.read(limit)
        # Avoid splitting a UTF-8 character between successive chunks.
        if start + len(raw) < length:
            for _ in range(3):
                try:
                    raw.decode('utf-8')
                    break
                except UnicodeDecodeError as exc:
                    if exc.reason != 'unexpected end of data':
                        break
                    extra = file_obj.read(1)
                    if not extra:
                        break
                    raw += extra
        else:
            # A writer might still be flushing the final multibyte character.
            try:
                raw.decode('utf-8')
            except UnicodeDecodeError as exc:
                if exc.reason == 'unexpected end of data':
                    raw = raw[:exc.start]
        offset = start + len(raw)
        return {
            'content': raw.decode('utf-8', errors='replace'),
            'cursor': f'{identity}:{offset:x}',
            'reset': reset,
        }
