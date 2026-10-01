import json


def compact_json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def json_loads_typed(value, default):
    try:
        parsed = json.loads(value or '')
    except Exception:
        return default
    return parsed if isinstance(parsed, type(default)) else default


def json_loads_dict(value) -> dict:
    return json_loads_typed(value or '{}', {})


def clone_json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False))

def json_dumps_or_default(value, default: str = '{}') -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return default


def json_loads_or_default(value, default=None):
    fallback = {} if default is None else default
    try:
        return json.loads(str(value or ''))
    except Exception:
        return fallback

