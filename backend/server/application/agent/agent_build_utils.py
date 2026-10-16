"""Shared source staging and Python Client config used by builder implementations."""
import json
import os
import shutil

from core.client_revision import build_client_revision_manifest

EXCLUDE_DIRS = {'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', '.idea', '.vscode'}  # 'runtime'
EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.pyd'}
EXCLUDE_FILE_PATTERNS = {'nohup.out', 'nohup.out.*'}


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
                   file_transfer_port: int,
                   build_version: str, server_web_scheme: str = 'http', server_web_host: str = ''):
    config_path = os.path.join(client_dir, 'client', 'config', 'config.py')
    server_web_host = (server_web_host or server_host).strip() or server_host
    revision_manifest = build_client_revision_manifest(source_dir)
    client_revision = str(revision_manifest.get('revision') or '')
    client_revision_parts = json.dumps(revision_manifest.get('parts') or {}, ensure_ascii=False, sort_keys=True)
    client_revision_files = json.dumps(revision_manifest.get('files') or {}, ensure_ascii=False, sort_keys=True)
    template = f'''import os

SERVER_HOST = "{server_host}"
SERVER_PORT = {server_port}
SERVER_ADDR = (SERVER_HOST, SERVER_PORT)

SERVER_WEB_SCHEME = "{server_web_scheme}"
SERVER_WEB_HOST = "{server_web_host}"
SERVER_WEB_PORT = {web_port}
SERVER_FILE_TRANSFER_PORT = SERVER_WEB_PORT + 1
UPLOAD_BASE_URL = f"{{SERVER_WEB_SCHEME}}://{{SERVER_WEB_HOST}}:{{SERVER_WEB_PORT}}"
FILE_TRANSFER_BASE_URL = f"{{SERVER_WEB_SCHEME}}://{{SERVER_WEB_HOST}}:{{SERVER_FILE_TRANSFER_PORT}}"

CLIENT_BUILD_VERSION = "{build_version}"
RUNTIME_CONFIG = {{
    'server_host': SERVER_HOST,
    'server_port': SERVER_PORT,
    'server_web_scheme': SERVER_WEB_SCHEME,
    'server_web_host': SERVER_WEB_HOST,
    'server_web_port': SERVER_WEB_PORT,
    'client_build_version': CLIENT_BUILD_VERSION,
}}
CLIENT_SOURCE_REVISION = "{client_revision}"
CLIENT_SOURCE_REVISION_PARTS = {client_revision_parts}
CLIENT_SOURCE_REVISION_FILES = {client_revision_files}
'''
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(template)
