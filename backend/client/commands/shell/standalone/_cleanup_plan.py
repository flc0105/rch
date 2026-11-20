"""Scan and apply the selected paths owned by Client clean."""

import fnmatch
import hashlib
import json
import os
import shutil
import stat
import sys
import time

from client.app.logging import get_client_log_path
from client.config.runtime_config_store import get_runtime_config_path
from client.runtime.client_util import get_client_bundle_download_dir, get_client_bundle_release_dir
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.temp_workspace import get_client_temp_root, get_temp_category_dir, path_contains_active_temp
from core.client_revision import is_bundle_archive


_TEMP_CATEGORIES = (
    'remote_job_temp', 'preview_temp', 'clipboard_temp', 'clipboard_helper_temp',
    'media_temp', 'archive_temp', 'client_logs', 'clipboard_staging', 'watchdog_heartbeats', 'watchdog_sessions',
)
_RELEASE_DIRECTORIES = ('bundle_old_releases', 'bundle_extracting_residue')
_PROBE_PATTERNS = ('.update_ready_*.json', '.update_startup_*.log')
_COUNT_KEYS = ('removed_files', 'removed_dirs', 'bytes_freed')


class ClientCleanupService:
    ITEMS = (
        *_TEMP_CATEGORIES[:4], 'runtime_config_temp', *_TEMP_CATEGORIES[4:],
        'bundle_old_releases', 'bundle_archive_residue', 'bundle_extracting_residue', 'bundle_probe_files',
    )
    ACTIVE_GRACE_SECONDS = 60
    ARCHIVE_GRACE_SECONDS = 300
    CLIPBOARD_STAGING_GRACE_SECONDS = 3600

    def __init__(self, *, checkpoint=None, progress_callback=None):
        self._checkpoint = checkpoint if checkpoint is not None else _noop
        self._progress = progress_callback if progress_callback is not None else _noop

    def plan(self) -> dict:
        items = []
        for name in self.ITEMS:
            self._checkpoint()
            item = _new_result(name)
            try:
                self._scan(name, item)
            except (CommandCancelledError, CommandTimeoutError):
                raise
            except OSError as exc:
                _record_scan_error(item, exc, next(iter(item['scanned_paths']), name))
            items.append(item)
            self._progress('scan_completed', item)
        return {'items': items}

    def _scan(self, name, item):
        directory, prune_dirs = _category_location(name)
        item['scanned_paths'].append(directory)
        if any(os.path.islink(path) for path in prune_dirs):
            return
        try:
            filenames = sorted(os.listdir(directory))
        except (FileNotFoundError, NotADirectoryError):
            return
        item['prune_dirs'] = prune_dirs
        item['has_empty_dirs'] = bool(prune_dirs) and not filenames

        current_release = _current_release(directory) if name in _RELEASE_DIRECTORIES else ''
        for filename in filenames:
            self._checkpoint()
            path = os.path.join(directory, filename)
            if not _matches_category(name, path):
                continue
            if path == current_release or path_contains_active_temp(path):
                item['skipped_paths'].append(path)
                continue
            try:
                signature, newest, counts = self._snapshot(path)
            except (CommandCancelledError, CommandTimeoutError):
                raise
            except OSError as exc:
                _record_scan_error(item, exc, path)
                continue
            if not self._eligible_runtime_path(name, path, newest):
                item['skipped_paths'].append(path)
                continue
            _add_counts(item, counts)
            item['paths'].append({'path': path, 'tree_signature': signature})

    def execute_plan(self, plan: dict, selected: set[str]) -> dict:
        """Apply only approved paths whose ownership and snapshot still match."""
        if not isinstance(plan, dict) or not isinstance(selected, set):
            raise ValueError('Invalid cleanup plan')
        categories = {item['name'] for item in plan.get('items', [])}
        if not selected.issubset(categories):
            raise ValueError('Unrecognized cleanup selection')

        items = []
        for item in plan.get('items', []):
            if item['name'] not in selected:
                continue
            self._progress('clean_started', item)
            result = self._apply_category(item)
            items.append(result)
            self._progress('clean_completed', result)
        return {
            'items': items,
            **{key: sum(item[key] for item in items) for key in _COUNT_KEYS},
            'error_count': sum(len(item['errors']) for item in items),
            'scan_error_count': sum(len(item['errors']) for item in plan['items']),
            'skipped_count': sum(bool(item['skipped_paths']) for item in items),
        }

    def _apply_category(self, item):
        name = item['name']
        result = _new_result(name)
        for key in ('skipped_paths', 'scanned_paths'):
            result[key].extend(item.get(key) or [])

        try:
            directory, prune_dirs = _category_location(name)
            current_release = _current_release(directory) if name in _RELEASE_DIRECTORIES else ''
        except OSError as exc:
            result['errors'].append(str(exc))
            return result
        seen = set()
        for entry in item['paths']:
            self._checkpoint()
            path = entry['path']
            if path in seen:
                continue
            seen.add(path)
            if (not os.path.isabs(path) or path != os.path.abspath(path)
                    or os.path.dirname(path) != directory
                    or any(os.path.islink(parent) for parent in prune_dirs)):
                result['skipped_paths'].append(path + ' (outside managed cleanup paths)')
                continue
            if not os.path.lexists(path):
                result['skipped_paths'].append(path + ' (missing after preview)')
                continue
            if not _matches_category(name, path):
                result['skipped_paths'].append(path + ' (outside managed cleanup paths)')
                continue
            if path == current_release or path_contains_active_temp(path):
                result['skipped_paths'].append(path + ' (active or not yet stale)')
                continue

            entries = []
            try:
                signature, newest, counts = self._snapshot(path, entries)
            except (CommandCancelledError, CommandTimeoutError):
                raise
            except FileNotFoundError:
                result['skipped_paths'].append(path + ' (missing after preview)')
                continue
            except OSError as exc:
                result['errors'].append(f'{path}: {exc}')
                continue
            if signature != entry['tree_signature']:
                result['skipped_paths'].append(path + ' (changed after preview)')
                continue
            if not self._eligible_runtime_path(name, path, newest) or path_contains_active_temp(path):
                result['skipped_paths'].append(path + ' (active or not yet stale)')
                continue
            _delete_path(path, entries, counts, result)

        if not any(os.path.islink(parent) for parent in prune_dirs):
            for directory in prune_dirs:
                if directory in item.get('prune_dirs', ()):
                    # rmdir itself refuses a directory that is no longer empty.
                    try:
                        os.rmdir(directory)
                    except OSError:
                        pass
        return result

    def _snapshot(self, path, entries=None):
        """Count and fingerprint metadata in the same walk, without following symlinks."""
        digest = hashlib.sha256()
        counts = dict.fromkeys(_COUNT_KEYS, 0)
        newest = 0
        for full_path, info in _tree_entries(path):
            self._checkpoint()
            relative = os.path.relpath(full_path, path)
            digest.update(repr((relative, info.st_dev, info.st_ino, info.st_mode,
                                info.st_size, info.st_mtime_ns, info.st_ctime_ns)).encode())
            newest = max(newest, info.st_mtime)
            is_directory = stat.S_ISDIR(info.st_mode)
            size = info.st_size if stat.S_ISREG(info.st_mode) else 0
            _count_entry(counts, is_directory, size)
            if entries is not None:
                entries.append((full_path, is_directory, size))
        return digest.hexdigest(), newest, counts

    def _eligible_runtime_path(self, category, path, newest) -> bool:
        age = time.time() - newest
        if category == 'client_logs':
            current_log = get_client_log_path()
            return age >= self.ACTIVE_GRACE_SECONDS and (
                not current_log or path != os.path.dirname(os.path.abspath(current_log))
            )
        if category == 'archive_temp':
            return age >= self.ARCHIVE_GRACE_SECONDS
        if category == 'clipboard_staging':
            # The macOS GUI-user staging directory is outside this cleanup scope.
            return sys.platform != 'darwin' and age >= self.CLIPBOARD_STAGING_GRACE_SECONDS
        if category == 'watchdog_heartbeats':
            return age >= self.ACTIVE_GRACE_SECONDS and self._stale_heartbeat(path)
        if category == 'watchdog_sessions':
            return age >= self.ACTIVE_GRACE_SECONDS and self._stale_watchdog_session(path)
        return True

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


def _category_location(name):
    if name in _TEMP_CATEGORIES:
        root = os.path.abspath(get_client_temp_root(create=False))
        directory = os.path.abspath(get_temp_category_dir(name, create=False))
        if directory == root or os.path.commonpath([directory, root]) != root:
            raise ValueError(f'Invalid cleanup category directory: {directory}')
        return directory, (directory, root)
    if name == 'runtime_config_temp':
        return os.path.dirname(os.path.abspath(get_runtime_config_path())), ()
    if name == 'bundle_archive_residue':
        return os.path.abspath(get_client_bundle_download_dir()), ()
    if name in (*_RELEASE_DIRECTORIES, 'bundle_probe_files'):
        return os.path.realpath(get_client_bundle_release_dir()), ()
    raise ValueError(f'Unknown cleanup item: {name}')


def _matches_category(category, path):
    name = os.path.basename(path)
    if category == 'runtime_config_temp':
        return fnmatch.fnmatch(name, '.rch_runtime_config_*.json.tmp')
    if category == 'bundle_archive_residue':
        return os.path.isfile(path) and is_bundle_archive(name)
    if category == 'bundle_probe_files':
        return os.path.isfile(path) and any(fnmatch.fnmatch(name, pattern) for pattern in _PROBE_PATTERNS)
    if category in _RELEASE_DIRECTORIES:
        # Extracting directories appear only in their own Preview category.
        return os.path.isdir(path) and not os.path.islink(path) and (
            ('.extracting.' in name) == (category == 'bundle_extracting_residue')
        ) and os.path.normcase(os.path.realpath(path)) == os.path.normcase(path)
    if category == 'client_logs':
        return name.startswith('client_') and os.path.isdir(path) and not os.path.islink(path)
    if category == 'watchdog_sessions':
        return (name.startswith('rch_process_recovery_watchdog_')
                and os.path.isdir(path) and not os.path.islink(path))
    if category in ('archive_temp', 'clipboard_staging'):
        return os.path.isdir(path) and not os.path.islink(path)
    if category == 'watchdog_heartbeats':
        base = name.removesuffix('.tmp')
        return (not os.path.islink(path) and base.startswith('client_local_heartbeat_watchdog_heartbeat_')
                and base.endswith('.json'))
    return category in _TEMP_CATEGORIES


def _current_release(root):
    # Resolve the running release even if a manifest is missing or cwd changed.
    paths = [sys.argv[0] if sys.argv else '', os.getcwd()]
    if not getattr(sys, 'frozen', False):
        paths.insert(0, __file__)
    for path in paths:
        if not path:
            continue
        try:
            relative = os.path.relpath(os.path.realpath(path), root)
        except ValueError:  # Different Windows drives.
            continue
        first = relative.split(os.sep, 1)[0]
        if first not in ('.', '..'):
            return os.path.join(root, first)
    return ''


def _tree_entries(path):
    info = os.lstat(path)
    yield path, info
    if stat.S_ISDIR(info.st_mode) and not _is_reparse_point(info):
        def raise_error(exc):
            raise exc

        for directory, dirs, files in os.walk(path, onerror=raise_error, followlinks=False):
            retained_dirs = []
            for name in sorted(dirs + files):
                entry = os.path.join(directory, name)
                entry_info = os.lstat(entry)
                yield entry, entry_info
                if stat.S_ISDIR(entry_info.st_mode) and not _is_reparse_point(entry_info):
                    retained_dirs.append(name)
            dirs[:] = retained_dirs


def _is_reparse_point(info):
    # Windows junctions can report as directories even with lstat.
    return bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _delete_path(path, entries, counts, result):
    try:
        if entries[0][1]:
            shutil.rmtree(path)
        else:
            os.remove(path)
    except FileNotFoundError as exc:
        # The root can disappear, or rmtree can fail after removing children.
        if os.path.lexists(path):
            result['errors'].append(f'{path}: {exc}')
    except OSError as exc:
        result['errors'].append(f'{path}: {exc}')
    else:
        _add_counts(result, counts)
        result['paths'].append(path)
        return

    # Count what actually disappeared when a recursive deletion only partly succeeded.
    removed = [entry for entry in entries if not os.path.lexists(entry[0])]
    for _, is_directory, size in removed:
        _count_entry(result, is_directory, size)
    if removed:
        result['paths'].append(path)


def _count_entry(result, is_directory, size):
    result['removed_dirs' if is_directory else 'removed_files'] += 1
    result['bytes_freed'] += size


def _record_scan_error(item, error, path):
    location = error.filename or path
    item['errors'].append(f'{location}: {error.strerror or str(error)}')


def _add_counts(result, counts):
    for key in _COUNT_KEYS:
        result[key] += counts[key]


def _new_result(name):
    return {
        'name': name,
        **dict.fromkeys(_COUNT_KEYS, 0),
        'paths': [],
        'scanned_paths': [],
        'skipped_paths': [],
        'errors': [],
        'prune_dirs': (),
    }


def _noop(*_args):
    pass
