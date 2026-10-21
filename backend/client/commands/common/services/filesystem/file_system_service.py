import os
import shutil
import stat as stat_module
import time

from client.commands.common.services.filesystem.path_resolver import PathResolver
from client.commands.common.services.filesystem.batch_file_result import BatchFileResult
from core.utils.text_encoding import encode_for_existing_file


class FileSystemService:
    """
    文件系统操作服务。
    """

    def __init__(self, path_resolver: PathResolver, run_checked=None, iter_checked=None):
        self.path_resolver = path_resolver
        self.run_checked = run_checked
        self.iter_checked = iter_checked

    def _run(self, func, *args, **kwargs):
        if self.run_checked is None:
            return func(*args, **kwargs)
        return self.run_checked(func, *args, **kwargs)

    def _iter(self, iterable, check_interval: int = 1):
        if self.iter_checked is None:
            return iterable
        return self.iter_checked(iterable, check_interval=check_interval)

    def build_directory_entry(self, entry):
        stat_result = self._run(entry.stat, follow_symlinks=False)
        is_dir = self._run(entry.is_dir, follow_symlinks=True)
        is_symlink = self._run(entry.is_symlink)
        is_hidden = self.is_hidden_entry(entry, stat_result)

        return {
            'name': entry.name,
            'path': os.path.abspath(entry.path),
            'is_dir': is_dir,
            'is_symlink': is_symlink,
            'is_hidden': is_hidden,
            'size': 0 if is_dir else stat_result.st_size,
            'modified_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_result.st_mtime))
        }

    def is_hidden_entry(self, entry, stat_result):
        if entry.name.startswith('.'):
            return True

        if os.name == 'nt':
            file_attrs = getattr(stat_result, 'st_file_attributes', 0)
            if file_attrs & getattr(stat_module, 'FILE_ATTRIBUTE_HIDDEN', 0):
                return True

        return False

    def _add_search_context(self, item: dict, root_directory: str, parent_path: str) -> dict:
        item['parent_path'] = os.path.abspath(parent_path)
        try:
            relative_path = os.path.relpath(item.get('path') or '', os.path.abspath(root_directory))
        except Exception:
            relative_path = item.get('name') or ''

        item['relative_path'] = '' if relative_path == '.' else relative_path
        return item

    def _collect_directory_entries(self, directory: str, recursive: bool = False, show_hidden: bool = False) -> list[dict]:
        root_directory = os.path.abspath(directory)
        collected = []

        def _scan(current_directory: str):
            child_directories = []

            with os.scandir(current_directory) as iterator:
                for entry in self._iter(iterator):
                    try:
                        item = self.build_directory_entry(entry)
                        self._add_search_context(item, root_directory, current_directory)
                        collected.append(item)

                        # 递归搜索时不跟随符号链接，避免目录环。
                        if recursive and item.get('is_dir') and not item.get('is_symlink'):
                            if show_hidden or not item.get('is_hidden'):
                                child_directories.append(entry.path)
                    except Exception:
                        continue

            for child_directory in child_directories:
                try:
                    _scan(child_directory)
                except Exception:
                    continue

        _scan(root_directory)
        return collected

    def list_child_directories(self, directory: str) -> dict:
        """
        列出指定目录下一层子目录，供 command autocomplete 复用。
        """
        return self._list_child_entries_by_type(directory, want_directory=True)

    def list_child_files(self, directory: str) -> dict:
        """
        列出指定目录下一层文件，供 command autocomplete 复用。
        """
        return self._list_child_entries_by_type(directory, want_directory=False)

    def list_child_paths(self, directory: str) -> dict:
        """
        列出指定目录下一层文件和目录，供 command autocomplete 复用。
        """
        return self._list_child_entries_by_type(directory, want_directory=None)

    def _list_child_entries_by_type(self, directory: str, want_directory: bool | None) -> dict:
        current_directory = os.path.abspath(directory)
        entries = []

        with os.scandir(current_directory) as iterator:
            for entry in self._iter(iterator):
                try:
                    is_directory = self._run(entry.is_dir, follow_symlinks=True)
                    if want_directory is not None and bool(is_directory) != bool(want_directory):
                        continue

                    entries.append({
                        'name': entry.name,
                        'path': os.path.abspath(entry.path),
                        'is_dir': bool(is_directory),
                    })
                except Exception:
                    continue

        entries.sort(key=lambda item: (not bool(item.get('is_dir')), str(item.get('name') or '').lower()))

        return {
            'current_path': current_directory,
            'entries': entries,
            'total': len(entries),
        }

    def browse_directory(
        self,
        directory: str,
        page=1,
        page_size=100,
        show_hidden=False,
        search_keyword: str = '',
        recursive_search=False,
    ) -> dict:
        page = self._normalize_positive_int(page, default=1, maximum=None)
        page_size = self._normalize_positive_int(page_size, default=100, maximum=500)
        show_hidden = self._normalize_bool(show_hidden)
        recursive_search = self._normalize_bool(recursive_search)
        search_keyword = str(search_keyword or '').strip()
        search_keyword_lower = search_keyword.lower()

        all_entries = self._collect_directory_entries(
            directory,
            recursive=bool(search_keyword_lower and recursive_search),
            show_hidden=show_hidden,
        )

        if search_keyword_lower:
            all_entries = [
                item for item in all_entries
                if search_keyword_lower in str(item.get('name') or '').lower()
            ]

        if search_keyword_lower and recursive_search:
            all_entries.sort(key=lambda item: (not item['is_dir'], str(item.get('relative_path') or item['name']).lower()))
        else:
            all_entries.sort(key=lambda item: (not item['is_dir'], item['name'].lower()))

        total_all = len(all_entries)
        total_hidden = sum(1 for item in all_entries if item.get('is_hidden'))

        if show_hidden:
            visible_entries = all_entries
        else:
            visible_entries = [
                item for item in all_entries
                if not item.get('is_hidden')
            ]

        total_visible = len(visible_entries)
        total_pages = max((total_visible + page_size - 1) // page_size, 1)

        if page > total_pages:
            page = total_pages

        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        paged_entries = visible_entries[start_index:end_index]

        return {
            'current_path': directory,
            'parent_path': self.path_resolver.build_parent_path(directory),
            'entries': paged_entries,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_visible': total_visible,
                'total_pages': total_pages,
                'returned': len(paged_entries),
            },
            'summary': {
                'total_all': total_all,
                'total_hidden': total_hidden,
                'show_hidden': show_hidden,
                'search_keyword': search_keyword,
                'recursive_search': bool(search_keyword_lower and recursive_search),
            }
        }

    def delete_target_path(self, target_path: str):
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
            return 1, f'Directory deleted: {target_path}'

        os.remove(target_path)
        return 1, f'File deleted: {target_path}'

    def delete_paths(self, paths: list) -> BatchFileResult:
        succeeded, errors = 0, []
        for raw_path in paths:
            try:
                path = str(raw_path or '').strip()
                if not path:
                    raise ValueError('Path is required')
                target = self.path_resolver.require_existing_path_from_arg(path)
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
                succeeded += 1
            except Exception as exc:
                errors.append(f'{raw_path}: {exc}')
        return BatchFileResult('delete', len(paths), succeeded, tuple(errors))

    def create_directory(self, target_path: str):
        if os.path.exists(target_path):
            raise FileExistsError(f'Path already exists: {target_path}')

        os.makedirs(target_path, exist_ok=False)

    def rename_target_path(self, old_path: str, new_name: str = '', new_path: str = '') -> str:
        if not os.path.exists(old_path):
            raise FileNotFoundError(f'Path not found: {old_path}')

        if new_path:
            target_path = self.path_resolver.resolve_target_path(new_path)
        else:
            if not new_name:
                raise ValueError('New name is required')
            target_path = os.path.join(os.path.dirname(old_path), new_name)

        if os.path.exists(target_path):
            raise FileExistsError(f'Target already exists: {target_path}')

        os.rename(old_path, target_path)
        return target_path

    def is_sub_path(self, parent_path: str, target_path: str) -> bool:
        try:
            common = os.path.commonpath([os.path.abspath(parent_path), os.path.abspath(target_path)])
            return common == os.path.abspath(parent_path)
        except Exception:
            return False

    def copy_or_move_single_path(self, source_path: str, destination_dir: str, operation: str):
        source_abs = os.path.abspath(source_path)
        destination_dir_abs = os.path.abspath(destination_dir)
        target_path = os.path.join(destination_dir_abs, os.path.basename(source_abs))

        if source_abs == target_path:
            raise ValueError(f'Source and target are the same: {source_abs}')

        if os.path.exists(target_path):
            raise FileExistsError(f'Target already exists: {target_path}')

        if os.path.isdir(source_abs) and self.is_sub_path(source_abs, destination_dir_abs):
            raise ValueError(f'Cannot {operation} a directory into itself or its subdirectory: {source_abs}')

        if operation == 'copy':
            if os.path.isdir(source_abs):
                shutil.copytree(source_abs, target_path)
            else:
                shutil.copy2(source_abs, target_path)
        elif operation == 'move':
            shutil.move(source_abs, target_path)
        else:
            raise ValueError(f'Unsupported operation: {operation}')

        return target_path

    def paste_paths(self, source_paths: list[str], destination_dir: str, operation: str) -> BatchFileResult:
        succeeded, errors = 0, []
        for source_path in source_paths:
            try:
                path = str(source_path or '').strip()
                if not path:
                    raise ValueError('Path is required')
                resolved = self.path_resolver.require_existing_path_from_arg(path)
                self.copy_or_move_single_path(resolved, destination_dir, operation)
                succeeded += 1
            except Exception as exc:
                errors.append(f'{source_path}: {exc}')
        return BatchFileResult(operation, len(source_paths), succeeded, tuple(errors), destination_dir)

    def save_file_content(self, file_path: str, content: str, encoding: str = 'utf-8') -> tuple[str, int, str]:
        target_path = self.path_resolver.require_existing_path_from_arg(file_path)
        if os.path.isdir(target_path):
            raise IsADirectoryError(f'Cannot write to directory: {target_path}')

        with open(target_path, 'rb') as f:
            original_bytes = f.read()
        encoded_bytes = encode_for_existing_file(content, encoding, original_bytes)
        with open(target_path, 'wb') as f:
            f.write(encoded_bytes)

        file_size = os.path.getsize(target_path)
        return target_path, file_size, encoding

    def _normalize_positive_int(self, value, default: int, maximum: int | None = None) -> int:
        try:
            normalized = int(value)
        except Exception:
            normalized = default

        if normalized <= 0:
            normalized = default
        if maximum is not None and normalized > maximum:
            normalized = maximum
        return normalized

    def _normalize_bool(self, value) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(value)