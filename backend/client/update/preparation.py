"""Build, download, verify and publish the immutable Python source bundle."""

import hashlib
import os
import shutil
import tempfile

from client.config.config import (
    SERVER_HOST, SERVER_PORT, SERVER_WEB_SCHEME, SERVER_WEB_HOST,
    SERVER_WEB_PORT, RUNTIME_CONFIG,
)
from client.runtime.client_util import (
    get_client_bundle_release_dir, get_client_bundle_download_dir,
    build_bundle_extract_dir,
)
from core.agent_build_contract import AgentBuilderKind
from core.external_tools.archive import safe_extract_zip_archive


BUILD_API_TIMEOUT = (15, 600)
DOWNLOAD_TIMEOUT = (15, 600)


def build_request(runtime_config=None):
    runtime_config = RUNTIME_CONFIG if runtime_config is None else runtime_config
    mode = str(runtime_config.get('connection_mode') or 'reverse').strip().lower()
    payload = {
        'server_host': SERVER_HOST, 'server_port': SERVER_PORT,
        'server_web_scheme': SERVER_WEB_SCHEME,
        'server_web_host': SERVER_WEB_HOST, 'web_port': SERVER_WEB_PORT,
        'target_os': 'bundle', 'builder': AgentBuilderKind.PYTHON.value,
        'target_arch': '', 'source': 'update',
        'connection_mode': mode,
    }
    if mode == 'bind':
        payload.update(bind_host=runtime_config['bind_host'], bind_port=runtime_config['bind_port'],
                       server_transport=str(runtime_config.get('server_transport') or 'tcp'))
    else:
        payload.update(
            server_transport=str(runtime_config.get('server_transport') or 'tcp'),
        )
    return payload


def _digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(path, expected):
    expected = str(expected or '').lower().strip()
    if len(expected) != 64 or any(ch not in '0123456789abcdef' for ch in expected):
        raise ValueError('Update build did not supply a valid SHA-256 digest')
    if _digest(path) != expected:
        raise ValueError('Downloaded Client bundle SHA-256 mismatch')


def publish_archive(archive_path, extract_dir):
    final_dir = os.path.abspath(extract_dir)
    release_dir = os.path.dirname(final_dir)
    if os.path.lexists(final_dir):
        if os.path.isdir(final_dir) and not os.path.islink(final_dir) and os.path.isfile(os.path.join(final_dir, 'rchclient.py')):
            return final_dir
        raise FileExistsError(f'Incomplete release already exists: {final_dir}')
    stage = tempfile.mkdtemp(prefix=os.path.basename(final_dir) + '.extracting.', dir=release_dir)
    try:
        safe_extract_zip_archive(archive_path, stage)
        if not os.path.isfile(os.path.join(stage, 'rchclient.py')):
            raise FileNotFoundError('rchclient.py not found after extract')
        try:
            os.rename(stage, final_dir)
        except OSError:
            if not (os.path.isdir(final_dir) and not os.path.islink(final_dir)
                    and os.path.isfile(os.path.join(final_dir, 'rchclient.py'))):
                raise
        return final_dir
    finally:
        shutil.rmtree(stage, ignore_errors=True)


class UpdatePreparation:
    def __init__(self, command):
        self.command = command

    def run(self):
        cmd = self.command
        cmd.emit_progress('Bundle building requested', level='info')
        meta = cmd.client_api.build_agent_bundle(build_request(), timeout=BUILD_API_TIMEOUT)
        cmd.emit_progress('Bundle building completed', level='success')
        releases = get_client_bundle_release_dir()
        filename = str(meta.get('file_name') or '')
        try:
            builder = AgentBuilderKind(meta.get('builder'))
        except (TypeError, ValueError) as exc:
            raise ValueError('Unexpected Client update bundle builder') from exc
        if builder is not AgentBuilderKind.PYTHON:
            raise ValueError('Update requires a Python source bundle')
        if (not filename or filename in ('.', '..') or filename.startswith('.')
                or os.path.basename(filename) != filename or '\\' in filename):
            raise ValueError('Unsafe Client update bundle filename')
        archive_path = os.path.join(get_client_bundle_download_dir(), filename)
        candidate_dir = build_bundle_extract_dir(releases, filename)
        cmd.emit_progress(f'Bundle downloading: {filename}', level='info')
        try:
            cmd.client_api.download_file(
                meta['download_url'], archive_path, timeout=DOWNLOAD_TIMEOUT,
                chunk_size=64 * 1024, checkpoint=cmd._checkpoint,
            )
            verify_archive(archive_path, meta.get('sha256'))
            cmd.emit_progress('Bundle verified (SHA-256)', level='success')
            cmd.emit_progress('Bundle extracting...', level='info')
            result = publish_archive(archive_path, candidate_dir)
            cmd.emit_progress(f'Bundle ready at {result}', level='success')
            return os.path.join(result, 'rchclient.py')
        finally:
            # No permanent ZIP download cache: the release is the installed copy.
            try:
                os.unlink(archive_path)
            except FileNotFoundError:
                pass
