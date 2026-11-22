"""Shared source staging and Python Client config used by builder implementations."""
import json
import os
import shutil

from core.client_revision import build_client_revision_manifest

EXCLUDE_DIRS = {'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', '.idea', '.vscode'}  # 'runtime'
EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.pyd'}
EXCLUDE_FILE_PATTERNS = {'nohup.out', 'nohup.out.*'}
BUNDLED_AGENT_PROFILE_RELATIVE = 'client/config/profiles/agent.json'


def copy_source_paths(source_dir: str, relative_paths, dst: str):
    os.makedirs(dst, exist_ok=True)
    ignore = shutil.ignore_patterns(
        *EXCLUDE_DIRS,
        *[f'*{ext}' for ext in EXCLUDE_EXTENSIONS],
        *EXCLUDE_FILE_PATTERNS,
    )
    for relative_path in relative_paths:
        source_path = os.path.join(source_dir, relative_path)
        if not os.path.exists(source_path):
            raise FileNotFoundError(f'Build source not found: {relative_path}')
        target_path = os.path.join(dst, relative_path)
        if os.path.isdir(source_path):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copytree(
                source_path,
                target_path,
                ignore=ignore,
                ignore_dangling_symlinks=True,
            )
        else:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)


def inject_python_client_config(source_dir: str, client_dir: str, server_host: str, server_port: int, web_port: int,
                   build_version: str, server_web_scheme: str = 'http', server_web_host: str = '',
                   listener_protocol: str = 'tcp', tls_fingerprint: str = '',
                   connection_mode: str = 'reverse', bind_host: str = '0.0.0.0', bind_port: int = 9443):
    """Stage built-agent defaults without replacing the source configuration loader."""
    revision_manifest = build_client_revision_manifest(source_dir)
    profile = {
        'server_transport': listener_protocol,
        'server_tls_fingerprint': tls_fingerprint,
        **({
            'server_host': server_host,
            'server_port': server_port,
            'server_web_scheme': server_web_scheme,
            'server_web_host': (server_web_host or server_host).strip() or server_host,
            'server_web_port': web_port,
        } if connection_mode == 'reverse' else {}),
        'connection_mode': connection_mode,
        'bind_host': bind_host,
        'bind_port': bind_port,
        'client_build_version': build_version,
        'client_source_revision': str(revision_manifest.get('revision') or ''),
        'client_source_revision_files': revision_manifest.get('files') or {},
    }
    profile_path = os.path.join(client_dir, *BUNDLED_AGENT_PROFILE_RELATIVE.split('/'))
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)
    with open(profile_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
        f.write('\n')
