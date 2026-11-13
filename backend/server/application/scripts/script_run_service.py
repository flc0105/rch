"""Prepare the same Script Control request for CLI and Web execution."""

import os

from core.utils.script_metadata import read_script_metadata_from_source, resolve_script_params


def prepare_script_control(scripts_root: str, script_name: str, params: dict) -> dict:
    name = str(script_name or '').strip().replace('\\', '/')
    if not name:
        raise ValueError('script_name is required')
    if not isinstance(params, dict):
        raise ValueError('params must be an object')
    root = os.path.realpath(scripts_root)
    path = os.path.realpath(os.path.join(root, name if name.endswith('.py') else name + '.py'))
    if os.path.commonpath((root, path)) != root:
        raise ValueError('Script path is outside the Server Script directory')
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Script not found: {script_name}')
    with open(path, 'rt', encoding='utf-8') as source:
        code = source.read()
    normalized_name = os.path.relpath(path, root).replace('\\', '/')
    if normalized_name.endswith('.py'):
        normalized_name = normalized_name[:-3]
    metadata = read_script_metadata_from_source(code, fallback_name=normalized_name)
    return {
        'script_name': normalized_name,
        'source': code,
        'params': resolve_script_params(metadata, params),
    }
