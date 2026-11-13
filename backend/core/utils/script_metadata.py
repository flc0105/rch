import ast
import json
import warnings
from copy import deepcopy

from core.metadata.parameters import coerce_param_value, normalize_param_specs, resolve_param_values
from core.metadata.source import extract_metadata_from_module_ast, find_metadata_dict_node
from core.platform.normalization import normalize_platforms
from core.protocol.script_execution import normalize_execution_schema

_METADATA_KEYS = ('SCRIPT_METADATA', 'script_metadata', 'metadata', 'META', 'meta')


def _parse_script_ast(text):
    try:
        # Catalog metadata scanning should not emit compile-time escape warnings
        # from user scripts. Python reports those when scripts are executed.
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning,
                                    message=r'invalid escape sequence')
            return ast.parse(text)
    except Exception:
        return None


def read_script_metadata_from_source(source_text: str, fallback_name: str = '') -> dict:
    tree = _parse_script_ast(str(source_text or ''))
    if tree is None:
        return {}
    metadata = extract_metadata_from_module_ast(tree, _METADATA_KEYS)
    return normalize_script_metadata(metadata, fallback_name=fallback_name) if metadata else {}


def rewrite_script_metadata_name(source_text: str, new_name: str) -> str:
    """Replace only the existing top-level metadata name literal, preserving source."""
    tree = _parse_script_ast(source_text)
    metadata = find_metadata_dict_node(tree, _METADATA_KEYS)
    if not isinstance(metadata, ast.Dict):
        return source_text
    # A dict's last repeated key is the effective one; nested parameter names
    # and other strings are not the script's identity.
    for key, value in reversed(list(zip(metadata.keys, metadata.values))):
        if isinstance(key, ast.Constant) and key.value == 'name':
            if isinstance(value, ast.Constant) and value.value == new_name:
                return source_text
            # AST columns are UTF-8 byte offsets, not Unicode character offsets.
            data = source_text.encode('utf-8')
            lines = data.splitlines(keepends=True)
            start = sum(map(len, lines[:value.lineno - 1])) + value.col_offset
            end = sum(map(len, lines[:value.end_lineno - 1])) + value.end_col_offset
            replacement = json.dumps(new_name, ensure_ascii=False).encode('utf-8')
            return (data[:start] + replacement + data[end:]).decode('utf-8')
    return source_text


def read_script_metadata_from_file(file_path: str, fallback_name: str = '') -> dict:
    try:
        with open(file_path, 'r', encoding='utf-8') as file_obj:
            return read_script_metadata_from_source(file_obj.read(), fallback_name=fallback_name)
    except Exception:
        return {}


def normalize_script_platforms(platforms) -> list[str]:
    return normalize_platforms(platforms, wildcard=True)


def normalize_script_metadata(metadata: dict | None, fallback_name: str = '') -> dict:
    if not isinstance(metadata, dict) or not metadata:
        return {}
    normalized = deepcopy(metadata)
    normalized.pop('api_grants', None)
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
    normalized['params'] = normalize_param_specs(metadata.get('params'))
    if 'execution' in metadata:
        normalized['execution'] = normalize_execution_schema(metadata['execution'])
    return normalized


def coerce_script_param_value(spec: dict, value):
    return coerce_param_value(spec, value)


def resolve_script_params(metadata: dict | None, raw_params: dict | None) -> dict:
    normalized_metadata = normalize_script_metadata(metadata or {})
    return resolve_param_values(
        normalized_metadata.get('params') or [],
        raw_params,
        coerce_value=coerce_script_param_value,
        missing_required_message=lambda name: f'Missing required script param: {name}',
    )
