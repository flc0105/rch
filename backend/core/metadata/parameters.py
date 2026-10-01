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
    'text': 'textarea',
    'multiline': 'textarea',
    'textarea': 'textarea',
    'remote_file': 'remote_file',
    'remote_files': 'remote_files',
    'remote_folder': 'remote_folder',
    'remote_folders': 'remote_folders',
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


def normalize_param_spec(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    name = str(item.get('name') or '').strip()
    if not name:
        return None

    normalized = deepcopy(item)
    param_type = normalize_param_type(item.get('type'))
    normalized['name'] = name
    normalized['label'] = str(item.get('label') or name).strip() or name
    normalized['type'] = param_type
    normalized['required'] = bool(item.get('required', False))
    normalized['description'] = str(item.get('description') or '').strip()
    normalized['default'] = item.get('default') if 'default' in item else None

    if 'min' in item:
        normalized['min'] = item.get('min')
    if 'max' in item:
        normalized['max'] = item.get('max')

    if 'options' in item:
        options = item.get('options')
        normalized['options'] = list(options) if isinstance(options, (list, tuple)) else []
    elif param_type == 'select':
        normalized['options'] = []

    if 'multiple' in item:
        normalized['multiple'] = bool(item.get('multiple'))
    elif param_type in REMOTE_PATH_MULTI_PARAM_TYPES:
        normalized['multiple'] = True

    if 'selection_mode' in item:
        normalized['selection_mode'] = str(item.get('selection_mode') or '').strip().lower()
    if 'initial_path' in item:
        normalized['initial_path'] = str(item.get('initial_path') or '').strip()

    return normalized


def normalize_param_specs(items) -> list[dict]:
    result = []
    for item in items or []:
        normalized = normalize_param_spec(item)
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


def coerce_path_list(value, param_name: str) -> list[str]:
    if value is None or value == '':
        return []
    if not isinstance(value, list):
        raise ValueError(f'Invalid path list param: {param_name}')

    result = []
    for item in value:
        text = str(item or '').strip()
        if text:
            result.append(text)
    return result


def is_missing_param_value(spec: dict, value) -> bool:
    if value is None or value == '':
        return True
    param_type = normalize_param_type(spec.get('type'))
    if param_type in REMOTE_PATH_MULTI_PARAM_TYPES and isinstance(value, list):
        return len(value) == 0
    return False


def empty_param_value(spec: dict):
    return [] if normalize_param_type(spec.get('type')) in REMOTE_PATH_MULTI_PARAM_TYPES else ''


def coerce_param_value(spec: dict, value):
    param_name = str(spec.get('name') or '').strip() or 'param'
    param_type = normalize_param_type(spec.get('type'))
    if param_type == 'integer':
        return apply_param_limits(spec, coerce_number(value, param_name, integer=True))
    if param_type == 'number':
        return apply_param_limits(spec, coerce_number(value, param_name, integer=False))
    if param_type == 'boolean':
        return coerce_boolean(value, param_name)
    if param_type == 'select':
        allowed = spec.get('options') or []
        text_value = str(value)
        if allowed and text_value not in [str(item) for item in allowed]:
            raise ValueError(f'Invalid option for {param_name}: {text_value}')
        return text_value
    if param_type in REMOTE_PATH_MULTI_PARAM_TYPES:
        return coerce_path_list(value, param_name)
    if param_type in REMOTE_PATH_PARAM_TYPES:
        if isinstance(value, list):
            raise ValueError(f'Invalid path param: {param_name}')
        return str(value or '').strip()
    return str(value)


def resolve_param_values(
    param_specs,
    raw_params,
    *,
    coerce_value: Callable[[dict, object], object] = coerce_param_value,
    missing_required_message: Callable[[str], str],
    require_required: bool = True,
    include_missing: bool = False,
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
        if not has_value or is_missing_param_value(spec, raw_value):
            if 'default' in spec and spec.get('default') is not None:
                raw_value = spec.get('default')
            elif spec.get('required') and require_required:
                raise ValueError(missing_required_message(name))
            elif include_missing:
                resolved[name] = empty_param_value(spec)
                continue
            else:
                continue
        resolved[name] = coerce_value(spec, raw_value)

    for key, value in raw.items():
        if key not in resolved:
            resolved[key] = value
    return resolved
