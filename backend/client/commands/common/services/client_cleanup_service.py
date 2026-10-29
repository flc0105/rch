import fnmatch
import json
import hashlib
import os
import shutil
import sys
import tempfile
import time

from core.utils.filesystem import safe_file_size
from core.client_revision import is_bundle_archive
from client.config.runtime_config_store import get_runtime_config_path
from client.runtime.client_util import get_client_bundle_release_dir, get_client_bundle_download_dir
from client.runtime.client_logging import get_client_log_path
from client.runtime.temp_workspace import (
    get_client_temp_root,
    get_temp_category_dir,
    path_contains_active_temp,
)


class ClientCleanupService:
    """Clean client-owned transient residue and obsolete update bundle files."""

    ITEMS = (
        'remote_job_temp',
        'preview_temp',
        'clipboard_temp',
        'clipboard_helper_temp',
        'runtime_config_temp',
        'media_temp',
        'archive_temp',
        'client_logs',
        'clipboard_staging',
        'watchdog_heartbeats',
        'watchdog_sessions',
        'bundle_old_releases',
        'bundle_archive_residue',
        'bundle_extracting_residue',
        'bundle_probe_files',
    )

    # Current Client paths are flat categories directly below the current Client temp root.
    # Expiration margins prevent `clean --no-confirm` from removing in-flight files.
    ACTIVE_GRACE_SECONDS = 60
    ARCHIVE_GRACE_SECONDS = 300
    CLIPBOARD_STAGING_GRACE_SECONDS = 3600

    LEGACY_TEMP_PATTERNS = {
        'remote_job_temp': ('rat_remote_*.py',),
        'preview_temp': ('rat_preview_*',),
        'clipboard_temp': ('rch_clipboard_upload_*',),
        'clipboard_helper_temp': (
            'rch_windows_clipboard_*.py',
            'rch_macos_clipboard_*.py',
        ),
        'media_temp': (),
    }

    def __init__(self, *, checkpoint=None, current_bundle_resolver=None):
        self.checkpoint = checkpoint
        self.current_bundle_resolver = current_bundle_resolver
        self._planning = False
        self._planned_paths = []
        self._planned_prune_dirs = []
        self._active_category = ''

    def plan(self) -> dict:
        """Read-only snapshot of cleanup candidates, grouped by the existing categories."""
        self._planning = True
        self._planned_paths = []
        self._planned_prune_dirs = []
        try:
            preview_result = self.clean()
            groups = []
            for item in preview_result['items']:
                paths = [entry for entry in self._planned_paths if entry['category'] == item['name']]
                prunes = [entry['path'] for entry in self._planned_prune_dirs
                          if entry['category'] == item['name']]
                groups.append({**item, 'paths': paths, 'prune_dirs': prunes})
            return {'items': groups}
        finally:
            self._planning = False
            self._planned_paths = []
            self._planned_prune_dirs = []
            self._active_category = ''

    def execute_plan(self, plan: dict, selected: set[str]) -> dict:
        """Execute only approved, snapshotted paths, refusing changed identities."""
        if not isinstance(plan, dict) or not isinstance(selected, set):
            raise ValueError('Invalid cleanup plan')
        categories = {item['name'] for item in plan.get('items', [])}
        if not selected.issubset(categories):
            raise ValueError('Unrecognized cleanup selection')
        items, seen = [], set()
        for item in plan.get('items', []):
            if item['name'] not in selected:
                continue
            result = self._new_result(item['name'])
            result['skipped_paths'].extend(item.get('skipped_paths') or [])
            result['errors'].extend(item.get('errors') or [])
            result['scanned_paths'].extend(item.get('scanned_paths') or [])
            for entry in item['paths']:
                self._checkpoint()
                path = entry['path']
                if path in seen:
                    continue
                seen.add(path)
                # A preview is a snapshot, not permission to remove files that
                # became active after it was produced. Re-evaluate live guards.
                if not self._eligible_runtime_path(item['name'], path):
                    result['skipped_paths'].append(path + ' (active or not yet stale)')
                    continue
                try:
                    info = os.lstat(path)
                    if (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns) != tuple(entry['identity']) \
                            or self._tree_signature(path) != entry['tree_signature']:
                        result['skipped_paths'].append(path + ' (changed after preview)')
                        continue
                except OSError:
                    result['skipped_paths'].append(path + ' (missing after preview)')
                    continue
                self._remove_path(path, result)
            for directory in item.get('prune_dirs') or []:
                # The original clean removed now-empty managed temp directories.
                # rmdir never deletes a directory that gained contents after scanning.
                self._prune_empty_directory(directory)
            items.append(result)
        return {
            'items': items,
            'removed_files': sum(i['removed_files'] for i in items),
            'removed_dirs': sum(i['removed_dirs'] for i in items),
            'bytes_freed': sum(i['bytes_freed'] for i in items),
            'error_count': sum(len(i['errors']) for i in items),
            'skipped_count': sum(bool(i['skipped'] or i['skipped_paths']) for i in items),
        }

    def _candidate_identity(self, path):
        info = os.lstat(path)
        return [info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns]

    @staticmethod
    def _tree_signature(path):
        """Freeze directory contents for Preview; never follow symlinked directories."""
        digest = hashlib.sha256()
        def record(absolute, relative):
            info = os.lstat(absolute)
            digest.update(repr((relative, info.st_dev, info.st_ino, info.st_mode,
                                info.st_size, info.st_mtime_ns, info.st_ctime_ns)).encode())
        record(path, '.')
        if os.path.isdir(path) and not os.path.islink(path):
            for parent, dirs, files in os.walk(path, followlinks=False):
                for name in sorted(dirs + files):
                    full = os.path.join(parent, name)
                    record(full, os.path.relpath(full, path))
        return digest.hexdigest()

    def _preview_path(self, path, result):
        try:
            identity = self._candidate_identity(path)
        except OSError as exc:
            result['errors'].append(f'{path}: {exc}')
            return
        if os.path.isfile(path) or os.path.islink(path):
            result['removed_files'] += 1
            result['bytes_freed'] += safe_file_size(path) if not os.path.islink(path) else 0
        elif os.path.isdir(path):
            result['removed_dirs'] += 1
            for current, dirs, files in os.walk(path, followlinks=False):
                result['removed_dirs'] += len(dirs)
                result['removed_files'] += len(files)
                for filename in files:
                    result['bytes_freed'] += safe_file_size(os.path.join(current, filename))
        result['paths'].append(path)
        self._planned_paths.append({
            'category': result['name'], 'path': path, 'identity': identity,
            'tree_signature': self._tree_signature(path),
        })

    def clean(self) -> dict:
        item_results = []
        for name in self.ITEMS:
            self._checkpoint()
            self._active_category = name
            handler = getattr(self, f'_clean_{name}', None)
            if handler is None:
                raise ValueError(f'Unknown cleanup item: {name}')
            try:
                result = handler()
            except Exception as exc:
                result = self._new_result(name)
                result['errors'].append(str(exc))
            item_results.append(result)
        self._active_category = ''

        return {
            'items': item_results,
            'removed_files': sum(item['removed_files'] for item in item_results),
            'removed_dirs': sum(item['removed_dirs'] for item in item_results),
            'bytes_freed': sum(item['bytes_freed'] for item in item_results),
            'error_count': sum(len(item['errors']) for item in item_results),
            'skipped_count': sum(1 for item in item_results if item.get('skipped')),
        }

    def _clean_remote_job_temp(self):
        return self._clean_temp_item('remote_job_temp')

    def _clean_preview_temp(self):
        return self._clean_temp_item('preview_temp')

    def _clean_clipboard_temp(self):
        return self._clean_temp_item('clipboard_temp')

    def _clean_clipboard_helper_temp(self):
        return self._clean_temp_item('clipboard_helper_temp')

    def _clean_media_temp(self):
        return self._clean_temp_item('media_temp')

    def _clean_archive_temp(self):
        return self._clean_managed_children('archive_temp')

    def _clean_client_logs(self):
        return self._clean_managed_children('client_logs')

    def _clean_clipboard_staging(self):
        # macOS hands these files to Finder under the console user's home;
        # they are intentionally outside the shared temp root.
        return self._clean_managed_children('clipboard_staging')

    def _clean_watchdog_heartbeats(self):
        return self._clean_managed_children('watchdog_heartbeats')

    def _clean_watchdog_sessions(self):
        return self._clean_managed_children('watchdog_sessions')

    def _clean_managed_children(self, name: str) -> dict:
        result = self._new_result(name)
        self._clean_managed_temp_category(name, result)
        return result

    def _clean_temp_item(self, name: str) -> dict:
        result = self._new_result(name)
        self._clean_managed_temp_category(name, result)
        self._clean_legacy_temp_patterns(name, result)
        return result

    def _clean_managed_temp_category(self, category: str, result: dict):
        root = os.path.abspath(get_client_temp_root(create=False))
        category_dir = os.path.abspath(get_temp_category_dir(category, create=False))
        self._note_scan(result, category_dir)
        if not os.path.isdir(root) or os.path.islink(root) or os.path.islink(category_dir):
            return

        # Flat layout: <Client temp root>/<category>/<item>. Do not invent
        # <Client temp root>/<unrelated-category>/<category> paths.
        self._clean_directory_children(category_dir, result)
        self._prune_empty_directory(category_dir)
        self._prune_empty_directory(root)

    def _clean_directory_children(self, directory: str, result: dict):
        if not os.path.isdir(directory) or os.path.islink(directory):
            return
        for child_name in sorted(os.listdir(directory)):
            self._checkpoint()
            child_path = os.path.abspath(os.path.join(directory, child_name))
            if path_contains_active_temp(child_path) or not self._eligible_runtime_path(result['name'], child_path):
                result['skipped_paths'].append(child_path)
                continue
            self._remove_path(child_path, result)

    @staticmethod
    def _old_enough(path: str, seconds: float) -> bool:
        """Do not delete actively written content just because its directory is old."""
        try:
            newest = os.lstat(path).st_mtime
            if os.path.isdir(path) and not os.path.islink(path):
                for parent, dirs, files in os.walk(path, followlinks=False):
                    for name in dirs + files:
                        newest = max(newest, os.lstat(os.path.join(parent, name)).st_mtime)
            return time.time() - newest >= seconds
        except OSError:
            return False

    @staticmethod
    def _pid_active(pid: object) -> bool:
        """Conservative POSIX existence check; never send signals on Windows."""
        try:
            value = int(pid)
            if value <= 0:
                return True
            if os.name == 'nt':
                # Never use os.kill(pid, 0) on Windows: it can terminate processes.
                import ctypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                open_process = kernel.OpenProcess
                open_process.argtypes = (ctypes.c_uint, ctypes.c_int, ctypes.c_uint)
                open_process.restype = ctypes.c_void_p
                handle = open_process(0x1000, False, value)  # QUERY_LIMITED_INFORMATION
                if not handle:
                    return ctypes.get_last_error() != 87  # INVALID_PARAMETER: PID absent
                kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint))
                kernel.GetExitCodeProcess.restype = ctypes.c_int
                kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
                kernel.CloseHandle.restype = ctypes.c_int
                try:
                    exit_code = ctypes.c_uint()
                    if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return True
                    return exit_code.value == 259  # STILL_ACTIVE
                finally:
                    kernel.CloseHandle(ctypes.c_void_p(handle))
            os.kill(value, 0)
            return True
        except ProcessLookupError:
            return False
        except (PermissionError, ValueError, TypeError, OverflowError, OSError):
            return True

    def _stale_heartbeat(self, path: str) -> bool:
        name = os.path.basename(path)
        base = name.removesuffix('.tmp')
        if not (base.startswith('client_local_heartbeat_watchdog_heartbeat_') and base.endswith('.json')):
            return False
        if not self._old_enough(path, self.ACTIVE_GRACE_SECONDS):
            return False
        heartbeat = path[:-4] if name.endswith('.tmp') else path
        if not os.path.isfile(heartbeat) or os.path.islink(heartbeat):
            return True  # orphaned old .tmp
        try:
            with open(heartbeat, encoding='utf-8') as stream:
                payload = json.load(stream)
            if isinstance(payload, dict) and payload.get('pid'):
                return not self._pid_active(payload['pid'])
        except (OSError, ValueError, TypeError):
            pass  # stale, malformed orphan
        return True

    def _stale_watchdog_session(self, path: str) -> bool:
        if not os.path.isdir(path) or os.path.islink(path):
            return False
        if not os.path.basename(path).startswith('rch_process_recovery_watchdog_'):
            return False
        if not self._old_enough(path, self.ACTIVE_GRACE_SECONDS):
            return False
        ready = os.path.join(path, 'ready.json')
        if not os.path.isfile(ready):
            return True  # abandoned startup directory
        try:
            with open(ready, encoding='utf-8') as stream:
                payload = json.load(stream)
            if not isinstance(payload, dict) or not payload.get('pid'):
                return True
            return not self._pid_active(payload['pid'])
        except (OSError, ValueError, TypeError):
            return False  # uncertain; keep supervisor state

    def _eligible_runtime_path(self, category: str, path: str) -> bool:
        if category == 'client_logs':
            if not os.path.isdir(path) or os.path.islink(path) or not os.path.basename(path).startswith('client_'):
                return False
            current_log = get_client_log_path()
            if current_log and path == os.path.dirname(os.path.abspath(current_log)):
                return False
            # No per-process metadata file: keep the current instance and
            # recently updated logs; older instances are preview candidates.
            return self._old_enough(path, self.ACTIVE_GRACE_SECONDS)
        if category == 'archive_temp':
            return os.path.isdir(path) and not os.path.islink(path) and self._old_enough(path, self.ARCHIVE_GRACE_SECONDS)
        if category == 'clipboard_staging':
            return (sys.platform != 'darwin' and os.path.isdir(path)
                    and not os.path.islink(path) and self._old_enough(path, self.CLIPBOARD_STAGING_GRACE_SECONDS))
        if category == 'watchdog_heartbeats':
            return not os.path.islink(path) and self._stale_heartbeat(path)
        if category == 'watchdog_sessions':
            return self._stale_watchdog_session(path)
        return True

    def _clean_legacy_temp_patterns(self, name: str, result: dict):
        patterns = self.LEGACY_TEMP_PATTERNS.get(name) or ()
        if not patterns:
            return

        temp_root = os.path.abspath(tempfile.gettempdir())
        managed_root = os.path.abspath(get_client_temp_root(create=False))
        for pattern in patterns:
            self._note_scan(result, os.path.join(temp_root, pattern))
        try:
            names = sorted(os.listdir(temp_root))
        except Exception:
            return

        for entry_name in names:
            self._checkpoint()
            if not any(fnmatch.fnmatch(entry_name, pattern) for pattern in patterns):
                continue
            path = os.path.abspath(os.path.join(temp_root, entry_name))
            if path == managed_root or path.startswith(managed_root + os.sep):
                continue
            if path_contains_active_temp(path):
                result['skipped_paths'].append(path)
                continue
            self._remove_path(path, result)

    def _clean_runtime_config_temp(self) -> dict:
        result = self._new_result('runtime_config_temp')
        config_path = os.path.abspath(get_runtime_config_path())
        directory = os.path.dirname(config_path) or '.'
        self._note_scan(result, directory)
        if not os.path.isdir(directory):
            return result

        patterns = (
            '.runtime_config_*.json.tmp',
            '.rch_runtime_config_*.json.tmp',
        )
        for name in sorted(os.listdir(directory)):
            self._checkpoint()
            if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                continue
            path = os.path.abspath(os.path.join(directory, name))
            if path_contains_active_temp(path):
                result['skipped_paths'].append(path)
                continue

            self._remove_path(path, result)
        return result

    def _clean_bundle_old_releases(self) -> dict:
        result = self._new_result('bundle_old_releases')
        release_dir, current_bundle_dir = self._bundle_context(result)
        self._note_scan(result, release_dir)
        if result['skipped']:
            return result

        for name in sorted(os.listdir(release_dir)):
            self._checkpoint()
            entry = os.path.join(release_dir, name)
            if os.path.islink(entry) or not os.path.isdir(entry):
                continue
            path = os.path.realpath(entry)
            if os.path.commonpath([release_dir, path]) != release_dir:
                continue
            if path == current_bundle_dir:
                result['skipped_paths'].append(path)
                continue
            self._remove_path(path, result)
        return result

    def _clean_bundle_archive_residue(self) -> dict:
        result = self._new_result('bundle_archive_residue')
        downloads_dir = os.path.abspath(get_client_bundle_download_dir())
        self._note_scan(result, downloads_dir)
        if not os.path.isdir(downloads_dir):
            return result

        for name in sorted(os.listdir(downloads_dir)):
            self._checkpoint()
            path = os.path.abspath(os.path.join(downloads_dir, name))
            if os.path.isfile(path) and is_bundle_archive(name):
                self._remove_path(path, result)
        return result

    def _clean_bundle_extracting_residue(self) -> dict:
        result = self._new_result('bundle_extracting_residue')
        release_dir, running_dir = self._bundle_context(result)
        self._note_scan(result, release_dir)
        if not os.path.isdir(release_dir):
            return result
        for name in sorted(os.listdir(release_dir)):
            self._checkpoint()
            if '.extracting.' not in name:
                continue
            entry = os.path.join(release_dir, name)
            if os.path.islink(entry) or not os.path.isdir(entry):
                continue
            path = os.path.realpath(entry)
            if os.path.commonpath([release_dir, path]) != release_dir:
                continue
            if path == running_dir:
                result['skipped_paths'].append(path)
                continue
            self._remove_path(path, result)
        return result

    def _clean_bundle_probe_files(self) -> dict:
        result = self._new_result('bundle_probe_files')
        release_dir = os.path.abspath(get_client_bundle_release_dir())
        self._note_scan(result, release_dir)
        if not os.path.isdir(release_dir):
            return result

        patterns = (
            '.update_ready_*.json',
            '.update_startup_*.log',
        )
        for name in sorted(os.listdir(release_dir)):
            self._checkpoint()
            if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                continue
            path = os.path.abspath(os.path.join(release_dir, name))
            if os.path.isfile(path):
                self._remove_path(path, result)
        return result

    def _bundle_context(self, result: dict) -> tuple[str, str]:
        release_dir = os.path.realpath(os.path.abspath(get_client_bundle_release_dir()))
        current_bundle_dir = ''
        if self.current_bundle_resolver is not None:
            current_bundle_dir = str(self.current_bundle_resolver(release_dir) or '').strip()
        current_bundle_dir = os.path.realpath(os.path.abspath(current_bundle_dir)) if current_bundle_dir else ''

        if not current_bundle_dir:
            # Protect the running release even if its bundle manifest is absent.
            for path in (os.path.abspath(sys.argv[0] or ''), os.getcwd()):
                candidate = os.path.realpath(path)
                if os.path.isfile(candidate):
                    candidate = os.path.dirname(candidate)
                if os.path.commonpath([release_dir, candidate]) != release_dir:
                    continue
                relative = os.path.relpath(candidate, release_dir)
                if relative != '.' and not relative.startswith('..'):
                    current_bundle_dir = os.path.join(release_dir, relative.split(os.sep, 1)[0])
                    break
        return release_dir, current_bundle_dir

    def _remove_path(self, path: str, result: dict):
        path = os.path.abspath(path)
        if path_contains_active_temp(path):
            result['skipped_paths'].append(path)
            return
        if self._planning:
            self._preview_path(path, result)
            return

        if os.path.isfile(path) or os.path.islink(path):
            size = safe_file_size(path)
            try:
                os.remove(path)
            except FileNotFoundError:
                return
            except Exception as exc:
                result['errors'].append(f'{path}: {exc}')
                return
            result['removed_files'] += 1
            result['bytes_freed'] += size
            result['paths'].append(path)
            return

        if not os.path.isdir(path):
            return

        file_count = 0
        dir_count = 1
        total_size = 0
        for current_root, dir_names, file_names in os.walk(path):
            dir_count += len(dir_names)
            for file_name in file_names:
                file_count += 1
                total_size += safe_file_size(os.path.join(current_root, file_name))

        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return
        except Exception as exc:
            result['errors'].append(f'{path}: {exc}')
            return

        result['removed_files'] += file_count
        result['removed_dirs'] += dir_count
        result['bytes_freed'] += total_size
        result['paths'].append(path)

    def _checkpoint(self):
        if self.checkpoint is not None:
            self.checkpoint()

    def _prune_empty_directory(self, path: str):
        if self._planning:
            entry = {'category': self._active_category, 'path': os.path.abspath(path)}
            if entry not in self._planned_prune_dirs:
                self._planned_prune_dirs.append(entry)
            return
        try:
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
        except Exception:
            pass

    @staticmethod
    def _note_scan(result: dict, path: str):
        normalized = os.path.abspath(path)
        if normalized not in result['scanned_paths']:
            result['scanned_paths'].append(normalized)

    @staticmethod
    def _new_result(name: str) -> dict:
        return {
            'name': str(name or '').strip(),
            'removed_files': 0,
            'removed_dirs': 0,
            'bytes_freed': 0,
            'paths': [],
            'scanned_paths': [],
            'skipped_paths': [],
            'errors': [],
            'skipped': False,
            'skip_reason': '',
        }
