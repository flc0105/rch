import ast
from copy import deepcopy
from typing import Callable

_PARAM_TYPE_ALIASES = {
    'int': 'integer',
    'integer': 'integer',
    'float': 'number',
    'number': 'number',
    'str': 'string',
    'string': 'string',
    'bool': 'boolean',
    'boolean': 'boolean',
    'select': 'select',
}

REMOTE_PATH_PARAM_TYPES = {
    'remote_file',
    'remote_folder',
}
REMOTE_PATH_MULTI_PARAM_TYPES = {
    'remote_files',
    'remote_folders',
}


def normalize_param_type(value: str) -> str:
    text = str(value or 'string').strip().lower()
    return _PARAM_TYPE_ALIASES.get(text, text or 'string')


def normalize_param_spec(item: dict, *, normalize_options: bool = False) -> dict | None:
    if not isinstance(item, dict):
        return None
    name = str(item.get('name') or '').strip()
    if not name:
        return None

    normalized = deepcopy(item)
    normalized['name'] = name
    normalized['type'] = normalize_param_type(item.get('type'))
    normalized['required'] = bool(item.get('required', False))
    normalized['description'] = str(item.get('description') or '').strip()
    normalized['default'] = item.get('default') if 'default' in item else None
    if 'min' in item:
        normalized['min'] = item.get('min')
    if 'max' in item:
        normalized['max'] = item.get('max')
    if normalize_options and 'options' in item and isinstance(item.get('options'), (list, tuple)):
        normalized['options'] = list(item.get('options'))
    return normalized


def normalize_param_specs(items, *, normalize_options: bool = False) -> list[dict]:
    result = []
    for item in items or []:
        normalized = normalize_param_spec(item, normalize_options=normalize_options)
        if normalized is not None:
            result.append(normalized)
    return result


def coerce_boolean(value, param_name: str):
    if isinstance(value, bool):
        return value
    text = str(value or '').strip().lower()
    if text in {'1', 'true', 'yes', 'on'}:
        return True
    if text in {'0', 'false', 'no', 'off'}:
        return False
    raise ValueError(f'Invalid boolean param: {param_name}')


def coerce_number(value, param_name: str, *, integer: bool = False):
    try:
        return int(str(value).strip()) if integer else float(str(value).strip())
    except Exception:
        expected = 'integer' if integer else 'number'
        raise ValueError(f'Invalid {expected} param: {param_name}')


def apply_param_limits(spec: dict, value):
    minimum = spec.get('min')
    maximum = spec.get('max')
    if minimum is not None and value < minimum:
        raise ValueError(f'Param "{spec.get("name", "")}" must be >= {minimum}')
    if maximum is not None and value > maximum:
        raise ValueError(f'Param "{spec.get("name", "")}" must be <= {maximum}')
    return value


def coerce_path_list_literal_or_single(value, _param_name: str) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        source = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            parsed = None
        if isinstance(parsed, (list, tuple, set)):
            source = list(parsed)
        else:
            source = [text]
    else:
        source = [value]

    result = []
    for item in source:
        text = str(item or '').strip()
        if text:
            result.append(text)
    return result


def coerce_path_list_csv_or_sequence(value, param_name: str) -> list[str]:
    if value is None or value == '':
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        return [item.strip() for item in text.split(',') if item.strip()]
    if not isinstance(value, (list, tuple, set)):
        raise ValueError(f'Invalid path list param: {param_name}')

    result = []
    for item in value:
        text = str(item or '').strip()
        if text:
            result.append(text)
    return result


def coerce_param_value(
    spec: dict,
    value,
    *,
    validate_select: bool = False,
    path_list_coercer: Callable[[object, str], list[str]] = coerce_path_list_csv_or_sequence,
):
    param_name = str(spec.get('name') or '').strip() or 'param'
    param_type = normalize_param_type(spec.get('type'))
    if param_type == 'integer':
        return apply_param_limits(spec, coerce_number(value, param_name, integer=True))
    if param_type == 'number':
        return apply_param_limits(spec, coerce_number(value, param_name, integer=False))
    if param_type == 'boolean':
        return coerce_boolean(value, param_name)
    if param_type == 'select' and validate_select:
        allowed = spec.get('options') or []
        text_value = str(value)
        if allowed and text_value not in allowed:
            raise ValueError(f'Invalid option for {param_name}: {text_value}')
        return text_value
    if param_type in REMOTE_PATH_MULTI_PARAM_TYPES:
        return path_list_coercer(value, param_name)
    if param_type in REMOTE_PATH_PARAM_TYPES:
        if isinstance(value, (list, tuple, set)):
            path_list = path_list_coercer(value, param_name)
            return path_list[0] if path_list else ''
        return str(value or '').strip()
    return str(value)


def resolve_param_values(
    param_specs,
    raw_params,
    *,
    coerce_value: Callable[[dict, object], object],
    missing_required_message: Callable[[str], str],
) -> dict:
    specs = list(param_specs or [])
    if not specs:
        return dict(raw_params or {}) if isinstance(raw_params, dict) else {}

    raw = dict(raw_params or {}) if isinstance(raw_params, dict) else {}
    resolved = {}
    for spec in specs:
        name = spec.get('name') or ''
        has_value = name in raw
        raw_value = raw.get(name)
        if not has_value or raw_value in (None, ''):
            if 'default' in spec and spec.get('default') is not None:
                raw_value = spec.get('default')
            elif spec.get('required'):
                raise ValueError(missing_required_message(name))
            else:
                continue
        resolved[name] = coerce_value(spec, raw_value)

    for key, value in raw.items():
        if key not in resolved:
            resolved[key] = value
    return resolved
