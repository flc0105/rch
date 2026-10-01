import ast
from copy import deepcopy

from core.metadata.parameters import (
    coerce_param_value,
    coerce_path_list_literal_or_single,
    normalize_param_specs,
    resolve_param_values,
)
from core.metadata.source import extract_metadata_from_module_ast
from core.platform.normalization import normalize_platform_alias, normalize_platforms

_METADATA_KEYS = ('SCRIPT_METADATA', 'script_metadata', 'metadata', 'META', 'meta')


def read_script_metadata_from_source(source_text: str, fallback_name: str = '') -> dict:
    text = str(source_text or '')
    if not text.strip():
        return {}
    try:
        tree = ast.parse(text)
    except Exception:
        return {}
    metadata = extract_metadata_from_module_ast(tree, _METADATA_KEYS)
    return normalize_script_metadata(metadata, fallback_name=fallback_name) if metadata else {}


def read_script_metadata_from_file(file_path: str, fallback_name: str = '') -> dict:
    try:
        with open(file_path, 'r', encoding='utf-8') as file_obj:
            return read_script_metadata_from_source(file_obj.read(), fallback_name=fallback_name)
    except Exception:
        return {}


def normalize_script_platform(value: str) -> str:
    return normalize_platform_alias(value, wildcard=True)


def normalize_script_platforms(platforms) -> list[str]:
    return normalize_platforms(platforms, wildcard=True)


def normalize_script_metadata(metadata: dict | None, fallback_name: str = '') -> dict:
    if not isinstance(metadata, dict) or not metadata:
        return {}
    normalized = deepcopy(metadata)
    fallback = str(fallback_name or '').strip()
    name = str(metadata.get('name') or fallback).strip() or fallback
    display_name = str(metadata.get('display_name') or name or fallback).strip() or name or fallback
    description = str(metadata.get('description') or '').strip()
    category = str(metadata.get('category') or '').strip()
    tags = [str(item).strip() for item in (metadata.get('tags') or []) if str(item).strip()]
    normalized['name'] = name
    normalized['display_name'] = display_name
    normalized['description'] = description
    normalized['category'] = category
    normalized['tags'] = tags
    normalized['platforms'] = normalize_script_platforms(metadata.get('platforms'))
    normalized['params'] = normalize_param_specs(metadata.get('params'), normalize_options=True)
    return normalized


def coerce_script_param_value(spec: dict, value):
    return coerce_param_value(
        spec,
        value,
        validate_select=True,
        path_list_coercer=coerce_path_list_literal_or_single,
    )


def resolve_script_params(metadata: dict | None, raw_params: dict | None) -> dict:
    normalized_metadata = normalize_script_metadata(metadata or {})
    return resolve_param_values(
        normalized_metadata.get('params') or [],
        raw_params,
        coerce_value=coerce_script_param_value,
        missing_required_message=lambda name: f'Missing required script param: {name}',
    )
