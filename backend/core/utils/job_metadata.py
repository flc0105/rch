import ast
from copy import deepcopy


_METADATA_KEYS = ('JOB_METADATA', 'job_metadata', 'metadata', 'META', 'meta')
_ANY_PLATFORM_ALIASES = {'*', 'all', 'any'}
_PLATFORM_ALIASES = {
    'darwin': 'mac',
    'mac': 'mac',
    'macos': 'mac',
    'osx': 'mac',
    'windows': 'win',
    'win': 'win',
    'win32': 'win',
    'nt': 'win',
    'linux': 'linux',
    'ios': 'ios',
}

_PARAM_TYPE_ALIASES = {
    'int': 'integer',
    'integer': 'integer',
    'float': 'number',
    'number': 'number',
    'str': 'string',
    'string': 'string',
    'bool': 'boolean',
    'boolean': 'boolean',
}

_REMOTE_PATH_PARAM_TYPES = {
    'remote_file',
    'remote_folder',
}
_REMOTE_PATH_MULTI_PARAM_TYPES = {
    'remote_files',
    'remote_folders',
}

_JOB_EXECUTION_MODE_ALIASES = {
    'inproc': 'inproc',
    'in_process': 'inproc',
    'in-process': 'inproc',
    'thread': 'inproc',
    'threaded': 'inproc',
    'subprocess': 'subprocess',
    'sub_process': 'subprocess',
    'sub-process': 'subprocess',
    'process': 'subprocess',
}



_JOB_EXECUTION_MODES = ('inproc', 'subprocess')

def _safe_literal_eval(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _extract_metadata_from_module_ast(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _METADATA_KEYS:
                    value = _safe_literal_eval(node.value)
                    if isinstance(value, dict):
                        return value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id in _METADATA_KEYS:
                value = _safe_literal_eval(node.value)
                if isinstance(value, dict):
                    return value
    return {}


def _extract_metadata_from_class_ast(tree):
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        for class_node in node.body:
            if isinstance(class_node, ast.Assign):
                for target in class_node.targets:
                    if isinstance(target, ast.Name) and target.id in _METADATA_KEYS:
                        value = _safe_literal_eval(class_node.value)
                        if isinstance(value, dict):
                            return value
            elif isinstance(class_node, ast.AnnAssign):
                target = class_node.target
                if isinstance(target, ast.Name) and target.id in _METADATA_KEYS:
                    value = _safe_literal_eval(class_node.value)
                    if isinstance(value, dict):
                        return value
    return {}


def read_job_metadata_from_source(source_text: str, fallback_name: str = '') -> dict:
    text = str(source_text or '')
    if not text.strip():
        return {}

    try:
        tree = ast.parse(text)
    except Exception:
        return {}

    metadata = _extract_metadata_from_module_ast(tree)
    if not metadata:
        metadata = _extract_metadata_from_class_ast(tree)

    return normalize_job_metadata(metadata, fallback_name=fallback_name)


def read_job_metadata_from_file(file_path: str, fallback_name: str = '') -> dict:
    try:
        with open(file_path, 'r', encoding='utf-8') as file_obj:
            return read_job_metadata_from_source(file_obj.read(), fallback_name=fallback_name)
    except Exception:
        return {}


def normalize_job_platform(value: str) -> str:
    text = str(value or '').strip().lower()
    if not text:
        return ''
    if text in _ANY_PLATFORM_ALIASES:
        return '*'
    return _PLATFORM_ALIASES.get(text, text)


def normalize_job_platforms(platforms) -> list[str]:
    if platforms is None:
        return []

    if isinstance(platforms, str):
        candidates = [platforms]
    elif isinstance(platforms, (list, tuple, set)):
        candidates = list(platforms)
    else:
        return []

    result = []
    seen = set()

    for item in candidates:
        normalized = normalize_job_platform(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def is_platform_supported(target_platform: str, allowed_platforms) -> bool:
    normalized_allowed = normalize_job_platforms(allowed_platforms)
    if not normalized_allowed or '*' in normalized_allowed:
        return True

    normalized_target = normalize_job_platform(target_platform)
    return bool(normalized_target and normalized_target in normalized_allowed)


def normalize_job_execution_mode(value, default: str = 'inproc') -> str:
    fallback = _JOB_EXECUTION_MODE_ALIASES.get(str(default or 'inproc').strip().lower(), 'inproc')
    text = str(value or '').strip().lower()
    if not text:
        return fallback
    normalized = _JOB_EXECUTION_MODE_ALIASES.get(text)
    if not normalized:
        raise ValueError(f'Unsupported background job execution mode: {value}')
    return normalized


def normalize_job_execution_allowed(value=None) -> list[str]:
    if value is None:
        return list(_JOB_EXECUTION_MODES)

    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        raise ValueError('Background job allowed execution modes must be a string or list')

    if not candidates:
        raise ValueError('Background job allowed execution modes cannot be empty')

    result = []
    seen = set()
    for item in candidates:
        normalized = normalize_job_execution_mode(item)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    if not result:
        raise ValueError('Background job allowed execution modes cannot be empty')
    return result


def _normalize_param_type(value: str) -> str:
    text = str(value or 'string').strip().lower()
    return _PARAM_TYPE_ALIASES.get(text, text or 'string')


def _normalize_param_spec(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None

    name = str(item.get('name') or '').strip()
    if not name:
        return None

    normalized = deepcopy(item)
    normalized['name'] = name
    normalized['type'] = _normalize_param_type(item.get('type'))
    normalized['required'] = bool(item.get('required', False))
    normalized['description'] = str(item.get('description') or '').strip()

    if 'default' in item:
        normalized['default'] = item.get('default')
    else:
        normalized['default'] = None

    if 'min' in item:
        normalized['min'] = item.get('min')
    if 'max' in item:
        normalized['max'] = item.get('max')

    return normalized


def normalize_job_metadata(metadata: dict | None, fallback_name: str = '') -> dict:
    if not isinstance(metadata, dict) or not metadata:
        return {}

    normalized = deepcopy(metadata)

    fallback = str(fallback_name or '').strip()
    name = str(metadata.get('name') or fallback).strip() or fallback
    display_name = str(metadata.get('display_name') or name or fallback).strip() or name or fallback
    description = str(metadata.get('description') or '').strip()
    platforms = normalize_job_platforms(metadata.get('platforms'))

    execution_meta = metadata.get('execution')
    execution_value = metadata.get('execution_mode')
    execution_default_explicit = execution_value not in (None, '')
    if execution_value in (None, ''):
        if isinstance(execution_meta, dict):
            execution_value = execution_meta.get('default') or execution_meta.get('mode')
            execution_default_explicit = execution_value not in (None, '')
        elif isinstance(execution_meta, str):
            execution_value = execution_meta
            execution_default_explicit = execution_value not in (None, '')

    allowed_value = None
    if isinstance(execution_meta, dict) and 'allowed' in execution_meta:
        allowed_value = execution_meta.get('allowed')
    elif 'allowed' in metadata:
        allowed_value = metadata.get('allowed')
    allowed_execution_modes = normalize_job_execution_allowed(allowed_value)

    if execution_default_explicit:
        execution_mode = normalize_job_execution_mode(execution_value, default='inproc')
        if execution_mode not in allowed_execution_modes:
            raise ValueError(
                f'Background job default execution mode "{execution_mode}" is not allowed: '
                f'{allowed_execution_modes}'
            )
    else:
        execution_mode = 'inproc' if 'inproc' in allowed_execution_modes else allowed_execution_modes[0]

    params = []
    for item in metadata.get('params') or []:
        normalized_item = _normalize_param_spec(item)
        if normalized_item is not None:
            params.append(normalized_item)

    normalized['name'] = name
    normalized['display_name'] = display_name
    normalized['description'] = description
    normalized['platforms'] = platforms
    normalized['execution_mode'] = execution_mode
    normalized['allowed'] = list(allowed_execution_modes)
    normalized_execution = deepcopy(execution_meta) if isinstance(execution_meta, dict) else {}
    normalized_execution['default'] = execution_mode
    normalized_execution['allowed'] = list(allowed_execution_modes)
    normalized['execution'] = normalized_execution
    normalized['params'] = params

    return normalized


def _coerce_boolean(value, param_name: str):
    if isinstance(value, bool):
        return value

    text = str(value or '').strip().lower()
    if text in {'1', 'true', 'yes', 'on'}:
        return True
    if text in {'0', 'false', 'no', 'off'}:
        return False
    raise ValueError(f'Invalid boolean param: {param_name}')


def _coerce_number(value, param_name: str, integer: bool = False):
    try:
        if integer:
            return int(str(value).strip())
        return float(str(value).strip())
    except Exception:
        expected = 'integer' if integer else 'number'
        raise ValueError(f'Invalid {expected} param: {param_name}')


def _apply_param_limits(spec: dict, value):
    minimum = spec.get('min')
    maximum = spec.get('max')

    if minimum is not None and value < minimum:
        raise ValueError(f'Param "{spec.get("name", "")}" must be >= {minimum}')

    if maximum is not None and value > maximum:
        raise ValueError(f'Param "{spec.get("name", "")}" must be <= {maximum}')

    return value


def _coerce_path_list(value, param_name: str) -> list[str]:
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

def coerce_job_param_value(spec: dict, value):
    param_name = str(spec.get('name') or '').strip() or 'param'
    param_type = _normalize_param_type(spec.get('type'))

    if param_type == 'integer':
        return _apply_param_limits(spec, _coerce_number(value, param_name, integer=True))

    if param_type == 'number':
        return _apply_param_limits(spec, _coerce_number(value, param_name, integer=False))

    if param_type == 'boolean':
        return _coerce_boolean(value, param_name)

    if param_type in _REMOTE_PATH_MULTI_PARAM_TYPES:
        return _coerce_path_list(value, param_name)

    if param_type in _REMOTE_PATH_PARAM_TYPES:
        if isinstance(value, (list, tuple, set)):
            path_list = _coerce_path_list(value, param_name)
            return path_list[0] if path_list else ''
        return str(value or '').strip()

    return str(value)


def resolve_job_params(metadata: dict | None, raw_params: dict | None) -> dict:
    normalized_metadata = normalize_job_metadata(metadata or {})
    param_specs = normalized_metadata.get('params') or []

    if not param_specs:
        return dict(raw_params or {}) if isinstance(raw_params, dict) else {}

    raw = dict(raw_params or {}) if isinstance(raw_params, dict) else {}
    resolved = {}

    for spec in param_specs:
        name = spec.get('name') or ''
        has_value = name in raw
        raw_value = raw.get(name)

        if not has_value or raw_value in (None, ''):
            if 'default' in spec and spec.get('default') is not None:
                raw_value = spec.get('default')
                has_value = True
            elif spec.get('required'):
                raise ValueError(f'Missing required job param: {name}')
            else:
                continue

        resolved[name] = coerce_job_param_value(spec, raw_value)

    for key, value in raw.items():
        if key not in resolved:
            resolved[key] = value

    return resolved
