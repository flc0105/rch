import json
import os
import shlex
import shutil
import sys
import tempfile
import threading
import time
from uuid import uuid4

from client.commands.platform.utils.ios_util import spawn
from client.commands.common.services.client_cleanup_service import ClientCleanupService
from client.commands.runtime.interrupts import interruptible
from client.config.config import (
    SERVER_HOST,
    SERVER_PORT,
    SERVER_WEB_HOST,
    SERVER_FILE_TRANSFER_PORT,
    SERVER_WEB_PORT,
    SERVER_WEB_SCHEME,
)
from core.external_tools.archive import safe_extract_zip_archive
from core.device.local_identity import get_local_identity
from client.runtime.client_util import (
    build_bundle_extract_dir,
    get_client_bundle_release_dir,
    spawn_detached_python_script,
)
from core.utils.decorator import desc
from core.utils.formatting import get_size
from core.utils.output_marker import success, info, warning, error


class CommandUpdateMixin:
    BUILD_API_TIMEOUT = (15, 600)
    DOWNLOAD_TIMEOUT = (15, 600)
    DOWNLOAD_CHUNK_SIZE = 64 * 1024
    UPDATE_READY_TIMEOUT_SECONDS = 10
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
            'file_transfer_port': SERVER_FILE_TRANSFER_PORT,
            'target_os': 'bundle',
            'builder': 'bundle',
            'target_arch': '',
            'source': 'update',
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
            ensure_not_interrupted=self._ensure_not_interrupted,
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

    def _clean_outdated_bundle_releases(self, release_dir: str, current_bundle_dir: str) -> dict:
        release_root = os.path.realpath(os.path.abspath(release_dir))
        current_root = os.path.realpath(os.path.abspath(current_bundle_dir))

        deleted_dirs = []
        deleted_zips = []
        skipped = []
        errors = []

        for name in sorted(os.listdir(release_root)):
            self._ensure_not_interrupted()

            path = os.path.realpath(os.path.join(release_root, name))

            try:
                if os.path.isdir(path):
                    if path == current_root:
                        skipped.append(path)
                        continue
                    shutil.rmtree(path)
                    deleted_dirs.append(path)
                    continue

                if os.path.isfile(path) and name.lower().endswith('.zip'):
                    os.remove(path)
                    deleted_zips.append(path)
                    continue
            except Exception as e:
                errors.append(f'{path}: {e}')

        return {
            'release_dir': release_root,
            'current_bundle_dir': current_root,
            'deleted_dirs': deleted_dirs,
            'deleted_zips': deleted_zips,
            'skipped': skipped,
            'errors': errors,
        }

    def _format_clean_outdated_releases_result(self, result: dict) -> str:
        lines = [
            success('Outdated bundle releases cleaned'),
            info(f'Release Dir: {result.get("release_dir", "")}'),
            info(f'Current Bundle Dir: {result.get("current_bundle_dir", "")}'),
            success(f'Deleted Version Dirs: {len(result.get("deleted_dirs") or [])}'),
            success(f'Deleted ZIP Files: {len(result.get("deleted_zips") or [])}'),
        ]

        deleted_dirs = result.get('deleted_dirs') or []
        deleted_zips = result.get('deleted_zips') or []
        errors = result.get('errors') or []

        if deleted_dirs:
            lines.append(warning('Deleted dirs:'))
            lines.extend(f'  {item}' for item in deleted_dirs)

        if deleted_zips:
            lines.append(warning('Deleted zips:'))
            lines.extend(f'  {item}' for item in deleted_zips)

        if errors:
            lines.append(error('Errors:'))
            lines.extend(f'  {item}' for item in errors)

        return '\n'.join(lines)


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
        deadline = time.time() + self.UPDATE_READY_TIMEOUT_SECONDS

        while time.time() < deadline:
            self._ensure_not_interrupted()

            if os.path.isfile(ready_path):
                with open(ready_path, 'r', encoding='utf-8') as file_obj:
                    payload = json.load(file_obj)
                if int(payload.get('pid') or 0) == int(process.pid):
                    stabilize_deadline = time.time() + self.UPDATE_READY_STABILIZE_SECONDS
                    while time.time() < stabilize_deadline:
                        self._ensure_not_interrupted()
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

    def _schedule_exit_after_update(self):
        guard_manager = getattr(self.socket, 'guard_manager', None)
        if guard_manager is not None:
            try:
                guard_manager.stop()
            except Exception:
                pass

        def _exit_current_client():
            time.sleep(self.UPDATE_EXIT_DELAY_SECONDS)
            try:
                self.socket.close()
            except Exception:
                pass
            os._exit(0)

        threading.Thread(
            target=_exit_current_client,
            name='ClientUpdateExit',
            daemon=True,
        ).start()

    @desc('Build, download, extract and launch the latest client bundle; use --keep-old to retain current client', group='session')
    @interruptible()
    def update(self, arg=''):
        ready_path = ''
        error_path = ''
        process = None
        update_ready = False

        try:
            options = self._parse_update_options(arg)

            self._send_info('Bundle building requested', 0)
            bundle_meta = self._request_update_bundle()
            self._send_success('Bundle building completed', 0)

            release_dir = get_client_bundle_release_dir()
            archive_path = os.path.join(release_dir, bundle_meta['file_name'])
            extract_dir = build_bundle_extract_dir(release_dir, bundle_meta['file_name'])

            self._send_info(f'Bundle downloading: {bundle_meta["file_name"]}', 0)
            self._download_bundle_archive(bundle_meta['download_url'], archive_path)
            self._send_success(f'Bundled downloaded successfully: {archive_path}', 0)

            current_bundle_dir = self._get_current_bundle_release_dir(release_dir)

            self._send_info('Bundle extracting...', 0)
            extract_dir = self._extract_update_bundle_safely(
                archive_path,
                extract_dir,
                current_bundle_dir,
            )
            self._send_success(f'Bundle ready at {extract_dir}')

            rchclient_path = os.path.join(extract_dir, 'rchclient.py')
            self._send_info(f'Preparing to launch script: {rchclient_path}', 0)

            if get_local_identity().os_alias == 'ios':
                self._send_success(
                    f'iOS detected, please restart Pythonista app and manually run script: {rchclient_path}',
                    eof=1,
                )
                return

            ready_path, error_path = self._build_update_ready_paths(release_dir)
            process = spawn_detached_python_script(
                rchclient_path,
                cwd=extract_dir,
                args=['--update-ready-file', ready_path],
                stderr_path=error_path,
            )
            ready_payload = self._wait_for_updated_client_ready(process, ready_path, error_path)
            update_ready = True

            new_client_id = str(ready_payload.get('client_id') or '').strip()
            new_revision = str(ready_payload.get('client_revision') or '').strip()
            result_text = f'Updated client connected successfully, PID: {process.pid}'
            if new_client_id:
                result_text = f'{result_text}, Client ID: {new_client_id}'
            if new_revision:
                result_text = f'{result_text}, Revision: {new_revision}'

            if options.get('keep_old'):
                self._send_success(f'{result_text}. Current client kept alive by --keep-old.', eof=1)
                return

            self._send_success(f'{result_text}. Current client will exit.', eof=1)
            self._schedule_exit_after_update()
        except Exception as e:
            if process is not None and process.poll() is None and not update_ready:
                self._stop_failed_update_process(process)
            self._send_error(f'Failed to update client bundle: {e}', eof=1)
        finally:
            self._cleanup_update_probe_files(ready_path, error_path)

    @desc('Clean outdated client bundle release directories and ZIP files', group='session')
    @interruptible()
    def clean_releases(self, arg=''):
        """
        清理默认 releases 目录里的旧 update bundle。
        当前只在自身运行于 update bundle 目录时执行。
        """
        try:
            release_dir = get_client_bundle_release_dir()
            current_bundle_dir = self._get_current_bundle_release_dir(release_dir)
            if not current_bundle_dir:
                self._send_warning(f'Skipped: current client is not running from default bundle releases directory', 0)
                self._send_warning(f'Default Release Dir: {release_dir}', 1)
                return

            result = self._clean_outdated_bundle_releases(release_dir, current_bundle_dir)
            return 1, self._format_clean_outdated_releases_result(result)
        except Exception as e:
            return self._send_error(f'Failed to clean outdated releases: {e}', 1)

    def _format_client_cleanup_result(self, result: dict) -> str:
        lines = [
            success('Client residue cleanup completed'),
            success(f'Deleted Files: {int(result.get("removed_files") or 0)}'),
            success(f'Deleted Directories: {int(result.get("removed_dirs") or 0)}'),
            success(f'Freed Size: {get_size(float(result.get("bytes_freed") or 0))}'),
        ]

        for item in result.get('items') or []:
            item_name = str(item.get('name') or '').strip()
            lines.append(info(
                f'[{item_name}] files={int(item.get("removed_files") or 0)} '
                f'dirs={int(item.get("removed_dirs") or 0)} '
                f'freed={get_size(float(item.get("bytes_freed") or 0))}'
            ))

            if item.get('skipped'):
                lines.append(warning(f'  Skipped: {item.get("skip_reason", "")}'))

            for path in item.get('paths') or []:
                lines.append(f'  deleted: {path}')

            for path in item.get('skipped_paths') or []:
                lines.append(f'  kept: {path}')

            for message in item.get('errors') or []:
                lines.append(error(f'  {message}'))

        return '\n'.join(lines)

    @desc('Clean all client-owned temporary residue and obsolete update bundle files', group='session')
    @interruptible()
    def clean(self, arg=''):
        """Clean all supported client residue. Usage: clean"""
        if str(arg or '').strip():
            return 0, error('Usage: clean')

        try:
            service = ClientCleanupService(
                ensure_not_interrupted=self._ensure_not_interrupted,
                current_bundle_resolver=self._get_current_bundle_release_dir,
            )
            result = service.clean()
            status = 0 if int(result.get('error_count') or 0) else 1
            return status, self._format_client_cleanup_result(result)
        except Exception as e:
            return 0, error(f'Failed to clean client residue: {e}')
