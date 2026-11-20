"""Build and hand off to a prepared Python Client release."""
import json
import os
import shlex
import shutil
import tempfile
import threading
import time
from uuid import uuid4

from client.commands.runtime.interrupts import cancel_policy
from client.config.config import (
    SERVER_HOST,
    SERVER_PORT,
    SERVER_WEB_HOST,
    SERVER_WEB_PORT,
    SERVER_WEB_SCHEME,
    RUNTIME_CONFIG,
)
from core.external_tools.archive import safe_extract_zip_archive
from core.agent_build_contract import AgentBuilderKind
from core.device.local_identity import get_local_identity
from client.runtime.client_util import (
    build_bundle_extract_dir,
    get_client_bundle_release_dir,
    get_client_bundle_download_dir,
    spawn_detached_python_script,
)
from client.commands.shell.decorators import shell_command


BUILD_API_TIMEOUT = (15, 600)
DOWNLOAD_TIMEOUT = (15, 600)
DOWNLOAD_CHUNK_SIZE = 64 * 1024
UPDATE_READY_TIMEOUT_SECONDS = 30
UPDATE_READY_STABILIZE_SECONDS = 2
UPDATE_READY_POLL_INTERVAL_SECONDS = 0.25
UPDATE_EXIT_DELAY_SECONDS = 0.5


@shell_command('Build, download, extract and launch the latest client bundle', group='maintenance', output='stream')
@cancel_policy('cooperative')
def update(self, arg=''):
    ready_path = ''
    error_path = ''
    process = None
    update_ready = False

    try:
        options = _parse_update_options(arg)

        self.emit_progress('Bundle building requested', level='info')
        bundle_meta = self.client_api.build_agent_bundle(
            _build_update_request_payload(), timeout=BUILD_API_TIMEOUT,
        )
        self.emit_progress('Bundle building completed', level='success')

        release_dir = get_client_bundle_release_dir()
        archive_dir = get_client_bundle_download_dir()
        archive_path = os.path.join(archive_dir, bundle_meta['file_name'])
        extract_dir = build_bundle_extract_dir(release_dir, bundle_meta['file_name'])

        self.emit_progress(f'Bundle downloading: {bundle_meta["file_name"]}', level='info')
        self.client_api.download_file(
            bundle_meta['download_url'], archive_path, timeout=DOWNLOAD_TIMEOUT,
            chunk_size=DOWNLOAD_CHUNK_SIZE, checkpoint=self._checkpoint,
        )
        self.emit_progress(f'Bundled downloaded successfully: {archive_path}', level='success')

        self.emit_progress('Bundle extracting...', level='info')
        extract_dir = _extract_update_bundle_safely(archive_path, extract_dir)
        self.emit_progress(f'Bundle ready at {extract_dir}', level='success')

        rchclient_path = os.path.join(extract_dir, 'rchclient.py')
        self.emit_progress(f'Preparing to launch script: {rchclient_path}', level='info')

        if get_local_identity().os_alias == 'ios':
            self.emit_completed(status='success', message=(
                f'iOS detected, please restart Pythonista app and manually run script: {rchclient_path}'
            ))
            return

        ready_path, error_path = _build_update_ready_paths(release_dir)
        process = spawn_detached_python_script(
            rchclient_path,
            cwd=extract_dir,
            args=['--update-ready-file', ready_path],
            stderr_path=error_path,
        )
        ready_payload = _wait_for_updated_client_ready(self, process, ready_path, error_path)
        _activate_updated_client_watchdog(self, process, ready_path)
        update_ready = True

        new_client_id = str(ready_payload.get('client_id') or '').strip()
        new_revision = str(ready_payload.get('client_revision') or '').strip()
        result_text = f'Updated client connected successfully, PID: {process.pid}'
        if new_client_id:
            result_text = f'{result_text}, Client ID: {new_client_id}'
        if new_revision:
            result_text = f'{result_text}, Revision: {new_revision}'

        if options.get('keep_old'):
            self.emit_completed(status='success', message=f'{result_text}. Current client kept alive by --keep-old.')
            return

        self.emit_completed(status='success', message=f'{result_text}. Current client will exit.')
        _schedule_exit_after_update(self.socket)
    except Exception as e:
        if process is not None and process.poll() is None and not update_ready:
            _stop_failed_update_process(process)
        self.emit_completed(status='error', message=f'Failed to update client bundle: {e}')
    finally:
        _cleanup_update_probe_files(ready_path, error_path)
        _cleanup_update_probe_files(
            f'{ready_path}.accepted' if ready_path else '',
            f'{ready_path}.adopted' if ready_path else '',
        )


def _build_update_request_payload() -> dict:
    # update 固定走 bundle 构建，不再依赖前台选择
    return {
        'server_host': SERVER_HOST,
        'server_port': SERVER_PORT,
        'server_web_scheme': SERVER_WEB_SCHEME,
        'server_web_host': SERVER_WEB_HOST,
        'web_port': SERVER_WEB_PORT,
        'target_os': 'bundle',
        'builder': AgentBuilderKind.PYTHON.value,
        'target_arch': '',
        'source': 'update',
        'server_transport': str(RUNTIME_CONFIG.get('server_transport') or 'tcp'),
        'server_tls_fingerprint': str(RUNTIME_CONFIG.get('server_tls_fingerprint') or ''),
    }

def _extract_update_bundle_safely(archive_path: str, extract_dir: str) -> str:
    """Publish a complete bundle and always remove this attempt's staging files."""
    final_dir = os.path.abspath(extract_dir)
    release_dir = os.path.dirname(final_dir)
    if _reuse_existing_release(final_dir):
        return final_dir

    temp_dir = tempfile.mkdtemp(
        prefix=f'{os.path.basename(final_dir)}.extracting.', dir=release_dir,
    )
    try:
        safe_extract_zip_archive(archive_path, temp_dir)
        rchclient_path = os.path.join(temp_dir, 'rchclient.py')
        if not os.path.isfile(rchclient_path):
            raise FileNotFoundError(f'rchclient.py not found after extract: {rchclient_path}')

        # Another update may have published the same bundle while we extracted it.
        if _reuse_existing_release(final_dir):
            return final_dir
        try:
            # The staging directory belongs only to this attempt. Never remove
            # a target directory created or used by another process.
            os.rename(temp_dir, final_dir)
        except OSError:
            if not _reuse_existing_release(final_dir):
                raise
        return final_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _reuse_existing_release(path: str) -> bool:
    if not os.path.lexists(path):
        return False
    if not os.path.islink(path) and os.path.isfile(os.path.join(path, 'rchclient.py')):
        return True
    raise FileExistsError(f'Incomplete release already exists: {path}')


def _parse_update_options(arg='') -> dict:
    tokens = shlex.split(str(arg or ''))
    keep_old = False

    for token in tokens:
        if token == '--keep-old':
            keep_old = True
            continue
        raise ValueError(f'Unsupported update option: {token}. Usage: update [--keep-old]')

    return {
        'keep_old': keep_old,
    }

def _build_update_ready_paths(release_dir: str) -> tuple[str, str]:
    token = uuid4().hex
    return (
        os.path.join(release_dir, f'.update_ready_{token}.json'),
        os.path.join(release_dir, f'.update_startup_{token}.log'),
    )

def _read_update_startup_error(error_path: str) -> str:
    if not error_path or not os.path.isfile(error_path):
        return ''
    try:
        with open(error_path, 'r', encoding='utf-8', errors='replace') as file_obj:
            text = file_obj.read().strip()
        if not text:
            return ''
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else text
    except Exception:
        return ''

def _stop_failed_update_process(process):
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass

def _wait_for_updated_client_ready(self, process, ready_path: str, error_path: str) -> dict:
    deadline = time.monotonic() + UPDATE_READY_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        self._checkpoint()

        if os.path.isfile(ready_path):
            with open(ready_path, 'r', encoding='utf-8') as file_obj:
                payload = json.load(file_obj)
            if int(payload.get('pid') or 0) == int(process.pid):
                stabilize_deadline = time.monotonic() + UPDATE_READY_STABILIZE_SECONDS
                while time.monotonic() < stabilize_deadline:
                    self._checkpoint()
                    return_code = process.poll()
                    if return_code is not None:
                        detail = _read_update_startup_error(error_path)
                        message = f'Updated client exited during startup verification, return code: {return_code}'
                        if detail:
                            message = f'{message}. {detail}'
                        raise RuntimeError(message)
                    time.sleep(UPDATE_READY_POLL_INTERVAL_SECONDS)
                return payload

        return_code = process.poll()
        if return_code is not None:
            detail = _read_update_startup_error(error_path)
            message = f'Updated client exited before handshake, return code: {return_code}'
            if detail:
                message = f'{message}. {detail}'
            raise RuntimeError(message)

        time.sleep(UPDATE_READY_POLL_INTERVAL_SECONDS)

    _stop_failed_update_process(process)
    detail = _read_update_startup_error(error_path)
    message = f'Updated client did not complete handshake within {UPDATE_READY_TIMEOUT_SECONDS} seconds'
    if detail:
        message = f'{message}. {detail}'
    raise RuntimeError(message)

def _cleanup_update_probe_files(*paths):
    for path in paths:
        if not path:
            continue
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

def _activate_updated_client_watchdog(self, process, ready_path):
    """Authorize the update candidate's supervisor only after PID verification."""
    accepted_path = f'{ready_path}.accepted'
    adopted_path = f'{ready_path}.adopted'
    with open(accepted_path, 'w', encoding='utf-8') as marker:
        marker.write('accepted\n')
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        self._checkpoint()
        if process.poll() is not None:
            raise RuntimeError('Updated Client exited during watchdog activation')
        if os.path.isfile(adopted_path):
            with open(adopted_path, 'r', encoding='utf-8') as marker:
                result = json.load(marker)
            if not result.get('ok'):
                raise RuntimeError(f'Updated Client watchdog activation failed: {result.get("error")}')
            return
        time.sleep(0.1)
    raise RuntimeError('Updated Client did not acknowledge watchdog activation')

def _close_update_connection(socket):
    socket.report_session_end('client_update', command='update')

    try:
        socket.close()
    except Exception:
        pass

def _schedule_exit_after_update(socket):
    process_recovery_watchdog_manager = getattr(socket, 'process_recovery_watchdog_manager', None)
    if process_recovery_watchdog_manager is not None:
        process_recovery_watchdog_manager.stop()

    watchdog_manager = getattr(socket, 'watchdog_manager', None)
    if watchdog_manager is not None:
        try:
            watchdog_manager.stop()
        except Exception:
            pass

    def _exit_current_client():
        time.sleep(UPDATE_EXIT_DELAY_SECONDS)
        _close_update_connection(socket)
        os._exit(0)

    threading.Thread(
        target=_exit_current_client,
        name='ClientUpdateExit',
        daemon=True,
    ).start()
