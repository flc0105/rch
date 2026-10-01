import fnmatch
import os
import shutil
import tempfile

from core.utils.filesystem import safe_file_size
from client.config.runtime_config_store import get_runtime_config_path
from client.runtime.client_util import get_client_bundle_release_dir
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
        'bundle_old_releases',
        'bundle_archive_residue',
        'bundle_extracting_residue',
        'bundle_probe_files',
    )

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

    def __init__(self, *, ensure_not_interrupted=None, current_bundle_resolver=None):
        self.ensure_not_interrupted = ensure_not_interrupted
        self.current_bundle_resolver = current_bundle_resolver

    def clean(self) -> dict:
        item_results = []
        for name in self.ITEMS:
            self._ensure_not_interrupted()
            handler = getattr(self, f'_clean_{name}', None)
            if handler is None:
                raise ValueError(f'Unknown cleanup item: {name}')
            try:
                result = handler()
            except Exception as exc:
                result = self._new_result(name)
                result['errors'].append(str(exc))
            item_results.append(result)

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

    def _clean_temp_item(self, name: str) -> dict:
        result = self._new_result(name)
        self._clean_managed_temp_category(name, result)
        self._clean_legacy_temp_patterns(name, result)
        return result

    def _clean_managed_temp_category(self, category: str, result: dict):
        root = get_client_temp_root(create=False)
        if not os.path.isdir(root):
            return

        category_dir = os.path.abspath(get_temp_category_dir(category, create=False))
        self._clean_directory_children(category_dir, result)
        self._prune_empty_directory(category_dir)

        # Older builds stored categories under an extra session directory.
        # That layout no longer exists; any matching nested category is residue.
        for entry_name in sorted(os.listdir(root)):
            self._ensure_not_interrupted()
            entry_path = os.path.abspath(os.path.join(root, entry_name))
            if not os.path.isdir(entry_path) or entry_path == category_dir:
                continue
            nested_category = os.path.abspath(os.path.join(entry_path, category))
            if not os.path.isdir(nested_category):
                continue
            self._clean_directory_children(nested_category, result)
            self._prune_empty_directory(nested_category)
            self._prune_empty_directory(entry_path)

        self._prune_empty_directory(root)

    def _clean_directory_children(self, directory: str, result: dict):
        if not os.path.isdir(directory):
            return
        for child_name in sorted(os.listdir(directory)):
            self._ensure_not_interrupted()
            child_path = os.path.abspath(os.path.join(directory, child_name))
            if path_contains_active_temp(child_path):
                result['skipped_paths'].append(child_path)
                continue
            self._remove_path(child_path, result)

    def _clean_legacy_temp_patterns(self, name: str, result: dict):
        patterns = self.LEGACY_TEMP_PATTERNS.get(name) or ()
        if not patterns:
            return

        temp_root = os.path.abspath(tempfile.gettempdir())
        managed_root = os.path.abspath(get_client_temp_root(create=False))
        try:
            names = sorted(os.listdir(temp_root))
        except Exception:
            return

        for entry_name in names:
            self._ensure_not_interrupted()
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
        if not os.path.isdir(directory):
            return result

        patterns = (
            '.runtime_config_*.json.tmp',
            '.rch_runtime_config_*.json.tmp',
        )
        for name in sorted(os.listdir(directory)):
            self._ensure_not_interrupted()
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
        if result['skipped']:
            return result

        for name in sorted(os.listdir(release_dir)):
            self._ensure_not_interrupted()
            path = os.path.realpath(os.path.join(release_dir, name))
            if not os.path.isdir(path):
                continue
            if '.extracting.' in name:
                continue
            if path == current_bundle_dir:
                result['skipped_paths'].append(path)
                continue
            if not os.path.isfile(os.path.join(path, 'rchclient.py')):
                continue
            self._remove_path(path, result)
        return result

    def _clean_bundle_archive_residue(self) -> dict:
        result = self._new_result('bundle_archive_residue')
        release_dir = os.path.abspath(get_client_bundle_release_dir())
        if not os.path.isdir(release_dir):
            return result

        for name in sorted(os.listdir(release_dir)):
            self._ensure_not_interrupted()
            path = os.path.abspath(os.path.join(release_dir, name))
            if os.path.isfile(path) and name.lower().endswith('.zip'):
                self._remove_path(path, result)
        return result

    def _clean_bundle_extracting_residue(self) -> dict:
        result = self._new_result('bundle_extracting_residue')
        release_dir = os.path.abspath(get_client_bundle_release_dir())
        if not os.path.isdir(release_dir):
            return result

        for name in sorted(os.listdir(release_dir)):
            self._ensure_not_interrupted()
            if '.extracting.' not in name:
                continue
            path = os.path.abspath(os.path.join(release_dir, name))
            if os.path.isdir(path):
                self._remove_path(path, result)
        return result

    def _clean_bundle_probe_files(self) -> dict:
        result = self._new_result('bundle_probe_files')
        release_dir = os.path.abspath(get_client_bundle_release_dir())
        if not os.path.isdir(release_dir):
            return result

        patterns = (
            '.update_ready_*.json',
            '.update_startup_*.log',
        )
        for name in sorted(os.listdir(release_dir)):
            self._ensure_not_interrupted()
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
            result['skipped'] = True
            result['skip_reason'] = 'Current client is not running from the default bundle releases directory'
        return release_dir, current_bundle_dir

    def _remove_path(self, path: str, result: dict):
        path = os.path.abspath(path)
        if path_contains_active_temp(path):
            result['skipped_paths'].append(path)
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

    def _ensure_not_interrupted(self):
        if self.ensure_not_interrupted is not None:
            self.ensure_not_interrupted()

    @staticmethod
    def _prune_empty_directory(path: str):
        try:
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
        except Exception:
            pass

    @staticmethod
    def _new_result(name: str) -> dict:
        return {
            'name': str(name or '').strip(),
            'removed_files': 0,
            'removed_dirs': 0,
            'bytes_freed': 0,
            'paths': [],
            'skipped_paths': [],
            'errors': [],
            'skipped': False,
            'skip_reason': '',
        }
