from client.commands.runtime.interrupts import cancel_policy
import json
import os
import shlex
import shutil
import sys
import tempfile
import threading
import time
from uuid import uuid4

from client.runtime.ios_util import spawn
from client.runtime.client_cleanup_service import ClientCleanupService
from client.config.config import (
    SERVER_HOST,
    SERVER_PORT,
    SERVER_WEB_HOST,
    SERVER_WEB_PORT,
    SERVER_WEB_SCHEME,
    RUNTIME_CONFIG,
)
from core.external_tools.archive import safe_extract_zip_archive
from core.client_revision import is_bundle_archive
from core.agent_build_contract import AgentBuilderKind
from core.device.local_identity import get_local_identity
from client.runtime.client_util import (
    build_bundle_extract_dir,
    get_client_bundle_release_dir,
    get_client_bundle_download_dir,
    spawn_detached_python_script,
)
from client.commands.shell.decorators import shell_command
from core.utils.formatting import get_size


class ShellMaintenanceCommands:
    BUILD_API_TIMEOUT = (15, 600)
    DOWNLOAD_TIMEOUT = (15, 600)
    DOWNLOAD_CHUNK_SIZE = 64 * 1024
    UPDATE_READY_TIMEOUT_SECONDS = 30
    UPDATE_READY_STABILIZE_SECONDS = 2
    UPDATE_READY_POLL_INTERVAL_SECONDS = 0.25
    UPDATE_EXIT_DELAY_SECONDS = 0.5

    def _build_update_request_payload(self) -> dict:
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

    def _request_update_bundle(self) -> dict:
        return self.client_api.build_agent_bundle(
            self._build_update_request_payload(),
            timeout=self.BUILD_API_TIMEOUT,
        )

    def _download_bundle_archive(self, download_url: str, archive_path: str):
        self.client_api.download_file(
            download_url,
            archive_path,
            timeout=self.DOWNLOAD_TIMEOUT,
            chunk_size=self.DOWNLOAD_CHUNK_SIZE,
            checkpoint=self._checkpoint,
        )

    def _get_current_bundle_release_dir(self, release_dir: str) -> str:
        """
        当前仅识别 update bundle 运行模式：
        ~/client_bundle/releases/<bundle_dir>/rchclient.py
        """
        if getattr(sys, 'frozen', False):
            return ''

        release_root = os.path.realpath(os.path.abspath(release_dir))
        candidates = []

        module_file = str(globals().get('__file__') or '').strip()
        if module_file:
            candidates.append(os.path.dirname(os.path.realpath(os.path.abspath(module_file))))

        argv0 = str(sys.argv[0] or '').strip()
        if argv0:
            candidates.append(os.path.dirname(os.path.realpath(os.path.abspath(argv0))))

        candidates.append(os.path.realpath(os.path.abspath(os.getcwd())))

        for current_dir in candidates:
            bundle_dir = self._resolve_bundle_release_dir_from_path(release_root, current_dir)
            if bundle_dir:
                return bundle_dir

        return ''

    def _resolve_bundle_release_dir_from_path(self, release_root: str, current_path: str) -> str:
        try:
            current_path = os.path.realpath(os.path.abspath(current_path))
            if os.path.commonpath([release_root, current_path]) != release_root:
                return ''

            relative_path = os.path.relpath(current_path, release_root)
            if not relative_path or relative_path == '.' or relative_path.startswith('..'):
                return ''

            release_name = relative_path.split(os.sep, 1)[0]
            bundle_dir = os.path.realpath(os.path.join(release_root, release_name))
            rchclient_path = os.path.join(bundle_dir, 'rchclient.py')

            if not os.path.isdir(bundle_dir):
                return ''
            if not os.path.isfile(rchclient_path):
                return ''

            return bundle_dir
        except Exception:
            return ''

    def _same_real_path(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        try:
            return os.path.realpath(os.path.abspath(left)) == os.path.realpath(os.path.abspath(right))
        except Exception:
            return False

    def _is_extracted_bundle_usable(self, extract_dir: str) -> bool:
        rchclient_path = os.path.join(extract_dir, 'rchclient.py')
        return os.path.isdir(extract_dir) and os.path.isfile(rchclient_path)

    def _extract_update_bundle_safely(self, archive_path: str, extract_dir: str, current_bundle_dir: str = '') -> str:
        """
        安全解压 update bundle。

        原则：
        1. 已存在可用目录时直接复用，避免同名 bundle 重复解压时删除正在运行的目录。
        2. 绝不删除当前进程所在的 bundle 目录。
        3. 先解压到临时目录，校验 rchclient.py 后再发布，避免中断后留下半成品目录。
        """
        release_dir = os.path.dirname(os.path.realpath(os.path.abspath(extract_dir)))
        final_dir = os.path.realpath(os.path.abspath(extract_dir))
        current_dir = os.path.realpath(os.path.abspath(current_bundle_dir)) if current_bundle_dir else ''

        if os.path.isdir(final_dir):
            if self._is_extracted_bundle_usable(final_dir):
                return final_dir

            if self._same_real_path(final_dir, current_dir):
                raise RuntimeError(f'Refuse to remove current running bundle directory: {final_dir}')

            shutil.rmtree(final_dir)

        temp_dir = tempfile.mkdtemp(
            prefix=f'{os.path.basename(final_dir)}.extracting.',
            dir=release_dir,
        )

        try:
            safe_extract_zip_archive(archive_path, temp_dir)

            rchclient_path = os.path.join(temp_dir, 'rchclient.py')
            if not os.path.isfile(rchclient_path):
                raise FileNotFoundError(f'rchclient.py not found after extract: {rchclient_path}')

            # 发布前再检查一次，兼容两个 update 几乎同时解同一个 bundle 的情况。
            if os.path.isdir(final_dir):
                if self._is_extracted_bundle_usable(final_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return final_dir

                if self._same_real_path(final_dir, current_dir):
                    raise RuntimeError(f'Refuse to replace current running bundle directory: {final_dir}')

                shutil.rmtree(final_dir)

            os.replace(temp_dir, final_dir)
            return final_dir

        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _parse_update_options(self, arg='') -> dict:
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

    def _build_update_ready_paths(self, release_dir: str) -> tuple[str, str]:
        token = uuid4().hex
        return (
            os.path.join(release_dir, f'.update_ready_{token}.json'),
            os.path.join(release_dir, f'.update_startup_{token}.log'),
        )

    def _read_update_startup_error(self, error_path: str) -> str:
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

    def _stop_failed_update_process(self, process):
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
        deadline = time.monotonic() + self.UPDATE_READY_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            self._checkpoint()

            if os.path.isfile(ready_path):
                with open(ready_path, 'r', encoding='utf-8') as file_obj:
                    payload = json.load(file_obj)
                if int(payload.get('pid') or 0) == int(process.pid):
                    stabilize_deadline = time.monotonic() + self.UPDATE_READY_STABILIZE_SECONDS
                    while time.monotonic() < stabilize_deadline:
                        self._checkpoint()
                        return_code = process.poll()
                        if return_code is not None:
                            detail = self._read_update_startup_error(error_path)
                            message = f'Updated client exited during startup verification, return code: {return_code}'
                            if detail:
                                message = f'{message}. {detail}'
                            raise RuntimeError(message)
                        time.sleep(self.UPDATE_READY_POLL_INTERVAL_SECONDS)
                    return payload

            return_code = process.poll()
            if return_code is not None:
                detail = self._read_update_startup_error(error_path)
                message = f'Updated client exited before handshake, return code: {return_code}'
                if detail:
                    message = f'{message}. {detail}'
                raise RuntimeError(message)

            time.sleep(self.UPDATE_READY_POLL_INTERVAL_SECONDS)

        self._stop_failed_update_process(process)
        detail = self._read_update_startup_error(error_path)
        message = f'Updated client did not complete handshake within {self.UPDATE_READY_TIMEOUT_SECONDS} seconds'
        if detail:
            message = f'{message}. {detail}'
        raise RuntimeError(message)

    def _cleanup_update_probe_files(self, *paths):
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

    def _close_update_connection(self):
        self.socket.report_session_end('client_update', command='update')

        try:
            self.socket.close()
        except Exception:
            pass

    def _schedule_exit_after_update(self):
        process_recovery_watchdog_manager = getattr(self.socket, 'process_recovery_watchdog_manager', None)
        if process_recovery_watchdog_manager is not None:
            process_recovery_watchdog_manager.stop()

        watchdog_manager = getattr(self.socket, 'watchdog_manager', None)
        if watchdog_manager is not None:
            try:
                watchdog_manager.stop()
            except Exception:
                pass

        def _exit_current_client():
            time.sleep(self.UPDATE_EXIT_DELAY_SECONDS)
            self._close_update_connection()
            os._exit(0)

        threading.Thread(
            target=_exit_current_client,
            name='ClientUpdateExit',
            daemon=True,
        ).start()

    @shell_command('Build, download, extract and launch the latest client bundle', group='maintenance', output='stream')
    @cancel_policy('cooperative')
    def update(self, arg=''):
        ready_path = ''
        error_path = ''
        process = None
        update_ready = False

        try:
            options = self._parse_update_options(arg)

            self.emit_progress('Bundle building requested', level='info')
            bundle_meta = self._request_update_bundle()
            self.emit_progress('Bundle building completed', level='success')

            release_dir = get_client_bundle_release_dir()
            archive_dir = get_client_bundle_download_dir()
            archive_path = os.path.join(archive_dir, bundle_meta['file_name'])
            extract_dir = build_bundle_extract_dir(release_dir, bundle_meta['file_name'])

            self.emit_progress(f'Bundle downloading: {bundle_meta["file_name"]}', level='info')
            self._download_bundle_archive(bundle_meta['download_url'], archive_path)
            self.emit_progress(f'Bundled downloaded successfully: {archive_path}', level='success')

            current_bundle_dir = self._get_current_bundle_release_dir(release_dir)

            self.emit_progress('Bundle extracting...', level='info')
            extract_dir = self._extract_update_bundle_safely(
                archive_path,
                extract_dir,
                current_bundle_dir,
            )
            self.emit_progress(f'Bundle ready at {extract_dir}', level='success')

            rchclient_path = os.path.join(extract_dir, 'rchclient.py')
            self.emit_progress(f'Preparing to launch script: {rchclient_path}', level='info')

            if get_local_identity().os_alias == 'ios':
                self.emit_completed(status='success', message=(
                    f'iOS detected, please restart Pythonista app and manually run script: {rchclient_path}'
                ))
                return

            ready_path, error_path = self._build_update_ready_paths(release_dir)
            process = spawn_detached_python_script(
                rchclient_path,
                cwd=extract_dir,
                args=['--update-ready-file', ready_path],
                stderr_path=error_path,
            )
            ready_payload = self._wait_for_updated_client_ready(process, ready_path, error_path)
            self._activate_updated_client_watchdog(process, ready_path)
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
            self._schedule_exit_after_update()
        except Exception as e:
            if process is not None and process.poll() is None and not update_ready:
                self._stop_failed_update_process(process)
            self.emit_completed(status='error', message=f'Failed to update client bundle: {e}')
        finally:
            self._cleanup_update_probe_files(ready_path, error_path)
            self._cleanup_update_probe_files(
                f'{ready_path}.accepted' if ready_path else '',
                f'{ready_path}.adopted' if ready_path else '',
            )

    @staticmethod
    def _cleanup_directory_label(item: dict) -> str:
        directories = [str(path) for path in (item.get('scanned_paths') or []) if str(path)]
        return ' | '.join(directories) if directories else 'managed cleanup directory'

    def _on_cleanup_progress(self, phase: str, item: dict):
        name = str(item.get('name') or 'cleanup').strip()
        files = int(item.get('removed_files') or 0)
        directories = int(item.get('removed_dirs') or 0)
        size = get_size(float(item.get('bytes_freed') or 0))
        errors = item.get('errors') or []

        if phase == 'scan_completed':
            if errors:
                self.emit_progress(f'Unable to scan {name} ({len(errors):,} errors)', level='error')
            elif item.get('skipped'):
                reason = str(item.get('skip_reason') or '').strip()
                suffix = f': {reason}' if reason else ''
                self.emit_progress(f'Skipped {name}{suffix}', level='warning')
            elif files or directories:
                self.emit_progress(
                    f'Scanned {name} — {ShellMaintenanceCommands._cleanup_directory_label(item)}: '
                    f'{files:,} files, {directories:,} directories, {size}',
                    level='info',
                )
            else:
                self.emit_progress(
                    f'Scanned {name} — {ShellMaintenanceCommands._cleanup_directory_label(item)}: nothing to clean',
                    level='info',
                )
            return

        if phase == 'clean_started':
            self.emit_progress(
                f'Cleaning {name} — {ShellMaintenanceCommands._cleanup_directory_label(item)}...',
                level='info',
            )
            return

        if phase == 'clean_completed':
            if errors:
                level = 'warning' if files or directories else 'error'
                self.emit_progress(
                    f'{name}: partially cleaned — {files:,} files, {directories:,} directories deleted; '
                    f'{size} freed; {len(errors):,} failed',
                    level=level,
                )
                for error in errors:
                    self.emit_progress(f'Failed to delete: {error}', level='error')
            elif files or directories:
                self.emit_progress(
                    f'Cleaned {name} — {files:,} files, {directories:,} directories deleted; {size} freed',
                    level='success',
                )
            else:
                self.emit_progress(f'{name}: nothing to delete', level='info')

    @staticmethod
    def _cleanup_completion(result: dict) -> tuple[str, str]:
        files = int(result.get('removed_files') or 0)
        directories = int(result.get('removed_dirs') or 0)
        freed = get_size(float(result.get('bytes_freed') or 0))
        errors = int(result.get('error_count') or 0)
        removed_any = files > 0 or directories > 0

        if errors and removed_any:
            status = 'partial'
            message = (
                f'Cleanup partially completed: {files:,} files and {directories:,} directories deleted; '
                f'{freed} freed; {errors:,} failed.'
            )
        elif errors:
            status = 'error'
            message = f'Cleanup failed: {errors:,} item(s) could not be deleted; nothing was removed.'
        elif removed_any:
            status = 'success'
            message = f'Cleanup completed: {files:,} files and {directories:,} directories deleted; {freed} freed.'
        else:
            status = 'success'
            message = 'Nothing to clean.'
        return status, message

    @staticmethod
    def _cleanup_scan_failure(plan: dict) -> tuple[int, dict]:
        from core.protocol.result_envelope import ResultEnvelope

        failed_items = [item for item in (plan.get('items') or []) if item.get('errors')]
        error_count = sum(len(item.get('errors') or []) for item in failed_items)
        names = ', '.join(str(item.get('name') or 'unknown') for item in failed_items)
        locations = f' ({names})' if names else ''
        message = (
            f'Cleanup scan failed{locations}: {error_count} error(s); '
            'nothing was deleted.'
        )
        return 0, ResultEnvelope(status='error', message=message).as_payload()

    @shell_command('Clean Client residue and obsolete bundle releases', group='maintenance', interaction=True)
    @cancel_policy('cooperative')
    def clean(self, arg=''):
        """Preview selectable cleanup categories; --no-confirm executes without Broker."""
        from core.protocol.result_envelope import ResultEnvelope

        options = str(arg or '').strip()
        if options not in ('', '--no-confirm'):
            return 0, 'Usage: clean [--no-confirm]'
        try:
            service = ClientCleanupService(
                checkpoint=self._checkpoint,
                current_bundle_resolver=self._get_current_bundle_release_dir,
                progress_callback=lambda phase, item: ShellMaintenanceCommands._on_cleanup_progress(self, phase, item),
            )
            self._set_timeout(240)
            self.emit_progress('Scanning cleanup directories...', level='info')
            plan = service.plan()
            if any(item.get('errors') for item in plan.get('items') or []):
                return ShellMaintenanceCommands._cleanup_scan_failure(plan)

            candidates = [
                entry for entry in plan['items']
                if entry['paths'] or any(
                    os.path.isdir(path) and not os.listdir(path)
                    for path in entry.get('prune_dirs') or []
                )
            ]
            if not candidates:
                return 1, ResultEnvelope(status='success', message='Nothing to clean.').as_payload()

            chosen = {entry['name'] for entry in candidates}
            if options == '--no-confirm':
                # An idle but live *other* Client cannot be proven inactive
                # without additional metadata; require manual Preview for logs.
                chosen.discard('client_logs')
            else:
                from client.runtime.execution.interaction_service import CommandInteractions
                rows = []
                for entry in candidates:
                    scanned_paths = [str(path) for path in (entry.get('scanned_paths') or [])]
                    rows.append({
                        'category': entry['name'],
                        'directory': ' | '.join(scanned_paths) if scanned_paths else 'managed cleanup directory',
                        'files': f"{int(entry.get('removed_files') or 0):,}",
                        'directories': f"{int(entry.get('removed_dirs') or 0):,}",
                        'size': get_size(float(entry.get('bytes_freed') or 0)),
                    })
                preview = {
                    'summary': [
                        {'label': 'Locations', 'value': str(len(rows))},
                        {'label': 'Files', 'value': f"{sum(i['removed_files'] for i in candidates):,}"},
                        {'label': 'Directories', 'value': f"{sum(i['removed_dirs'] for i in candidates):,}"},
                        {'label': 'Size', 'value': get_size(sum(float(i['bytes_freed'] or 0) for i in candidates))},
                    ],
                    'columns': [
                        {'key': 'category', 'label': 'Cleanup item'},
                        {'key': 'directory', 'label': 'Directory'},
                        {'key': 'files', 'label': 'Files'},
                        {'key': 'directories', 'label': 'Directories'},
                        {'key': 'size', 'label': 'Size'},
                    ],
                    'rows': rows,
                    'row_ids': [entry['name'] for entry in candidates],
                    'notice': 'The selected cleanup directories will be permanently cleaned. The current running release is protected.',
                }
                self.emit_progress('Waiting for cleanup approval...', level='info')
                chosen = set(CommandInteractions(self).select_preview_rows(
                    'Delete selected Client residue?', preview,
                    title='Client Cleanup — Delete Plan'))
                if not chosen:
                    return 1, ResultEnvelope(
                        status='success', message='No cleanup categories selected; nothing was deleted.'
                    ).as_payload()

            if not chosen:
                return 1, ResultEnvelope(
                    status='success', message='No safe cleanup targets selected; nothing was deleted.'
                ).as_payload()

            result = service.execute_plan(plan, chosen)
            final_status, final_message = ShellMaintenanceCommands._cleanup_completion(result)
            return (1 if final_status in ('success', 'partial') else 0), ResultEnvelope(
                status=final_status, message=final_message,
            ).as_payload()
        except Exception as exc:
            return 0, f'Failed to clean Client residue: {exc}'
