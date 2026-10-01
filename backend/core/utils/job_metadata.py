import ast
from copy import deepcopy

from core.metadata.parameters import (
    coerce_param_value,
    normalize_param_specs,
    resolve_param_values,
)
from core.metadata.source import extract_metadata_from_class_ast, extract_metadata_from_module_ast
from core.platform.normalization import (
    is_platform_supported as _is_platform_supported,
    normalize_platform_alias,
    normalize_platforms,
)

_METADATA_KEYS = ('JOB_METADATA', 'job_metadata', 'metadata', 'META', 'meta')
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


def read_job_metadata_from_source(source_text: str, fallback_name: str = '') -> dict:
    text = str(source_text or '')
    if not text.strip():
        return {}
    try:
        tree = ast.parse(text)
    except Exception:
        return {}
    metadata = extract_metadata_from_module_ast(tree, _METADATA_KEYS)
    if not metadata:
        metadata = extract_metadata_from_class_ast(tree, _METADATA_KEYS)
    return normalize_job_metadata(metadata, fallback_name=fallback_name)


def read_job_metadata_from_file(file_path: str, fallback_name: str = '') -> dict:
    try:
        with open(file_path, 'r', encoding='utf-8') as file_obj:
            return read_job_metadata_from_source(file_obj.read(), fallback_name=fallback_name)
    except Exception:
        return {}


def normalize_job_platform(value: str) -> str:
    return normalize_platform_alias(value, wildcard=True)


def normalize_job_platforms(platforms) -> list[str]:
    return normalize_platforms(platforms, wildcard=True)


def is_platform_supported(target_platform: str, allowed_platforms) -> bool:
    return _is_platform_supported(target_platform, allowed_platforms)


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


def normalize_job_metadata(metadata: dict | None, fallback_name: str = '') -> dict:
    if not isinstance(metadata, dict) or not metadata:
        return {}
    normalized = deepcopy(metadata)
    fallback = str(fallback_name or '').strip()
    name = str(metadata.get('name') or fallback).strip() or fallback
    display_name = str(metadata.get('display_name') or name or fallback).strip() or name or fallback
    description = str(metadata.get('description') or '').strip()

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

    normalized['name'] = name
    normalized['display_name'] = display_name
    normalized['description'] = description
    normalized['platforms'] = normalize_job_platforms(metadata.get('platforms'))
    normalized['execution_mode'] = execution_mode
    normalized['allowed'] = list(allowed_execution_modes)
    normalized_execution = deepcopy(execution_meta) if isinstance(execution_meta, dict) else {}
    normalized_execution['default'] = execution_mode
    normalized_execution['allowed'] = list(allowed_execution_modes)
    normalized['execution'] = normalized_execution
    normalized['params'] = normalize_param_specs(metadata.get('params'))
    return normalized


def coerce_job_param_value(spec: dict, value):
    return coerce_param_value(spec, value)


def resolve_job_params(metadata: dict | None, raw_params: dict | None) -> dict:
    normalized_metadata = normalize_job_metadata(metadata or {})
    return resolve_param_values(
        normalized_metadata.get('params') or [],
        raw_params,
        coerce_value=coerce_job_param_value,
        missing_required_message=lambda name: f'Missing required job param: {name}',
    )
