import glob
import os
import shutil
import tempfile
from pathlib import Path

from werkzeug.utils import secure_filename

from core.utils.script_metadata import read_script_metadata_from_file, rewrite_script_metadata_name


class ScriptCatalogService:
    def __init__(self, scripts_root_dir: str):
        self.scripts_root_dir = os.path.abspath(scripts_root_dir)
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(self.scripts_root_dir, exist_ok=True)

    def _normalize_relative_path(self, value: str) -> str:
        value = str(value or '').replace('\\', '/').lstrip('/')
        parts = []
        for part in value.split('/'):
            part = part.strip()
            if not part or part in ('.', '..'):
                continue
            parts.append(part)
        return '/'.join(parts)

    def _normalize_script_name(self, name: str) -> str:
        normalized = self._normalize_relative_path(name)
        if normalized.endswith('.py'):
            return normalized
        return normalized + '.py' if normalized else ''

    def _normalize_directory_path(self, directory: str) -> str:
        return self._normalize_relative_path(directory)

    def _resolve_abs_path(self, relative_path: str) -> str:
        safe_relative_path = self._normalize_relative_path(relative_path)
        abs_path = os.path.abspath(os.path.join(self.scripts_root_dir, safe_relative_path))
        if abs_path != self.scripts_root_dir and not abs_path.startswith(self.scripts_root_dir + os.sep):
            raise ValueError('Invalid script path')
        return abs_path

    def _build_script_item(self, file_path: str) -> dict:
        rel_path = os.path.relpath(file_path, self.scripts_root_dir)
        path = rel_path.replace('\\', '/')
        script_name = path[:-3] if path.endswith('.py') else path
        metadata = read_script_metadata_from_file(file_path, fallback_name=script_name)
        display_name = str(metadata.get('display_name') or Path(path).stem).strip() or Path(path).stem
        description = str(metadata.get('description') or '').strip()
        return {
            'name': script_name,
            'script_name': script_name,
            'path': path,
            'display_name': display_name,
            'description': description,
            'metadata': metadata,
            'size': os.path.getsize(file_path),
            'source': 'script',
            'kind': 'script',
        }

    def _build_directory_item(self, dir_path: str) -> dict:
        rel_path = os.path.relpath(dir_path, self.scripts_root_dir)
        normalized_path = '' if rel_path in ('.', '') else rel_path.replace('\\', '/')
        label = normalized_path.split('/')[-1] if normalized_path else 'root'
        return {
            'key': f'dir:{normalized_path or "."}',
            'path': normalized_path,
            'label': label,
            'kind': 'directory',
        }

    def list_scripts(self) -> list[dict]:
        items = []
        pattern = os.path.join(self.scripts_root_dir, '**/*.py')
        for file_path in glob.iglob(pattern, recursive=True):
            if not os.path.isfile(file_path):
                continue
            items.append(self._build_script_item(file_path))
        return sorted(items, key=lambda x: x['path'])

    # def list_directories(self) -> list[dict]:
    #     directories = {self.scripts_root_dir}
    #     for current_root, dir_names, _ in os.walk(self.scripts_root_dir):
    #         directories.add(os.path.abspath(current_root))
    #         for dir_name in dir_names:
    #             directories.add(os.path.abspath(os.path.join(current_root, dir_name)))
    #     return [self._build_directory_item(path) for path in sorted(directories)]

    def list_directories(self) -> list[dict]:
        directories = {self.scripts_root_dir}
        ignored_dir_names = {'__pycache__', '__MACOSX'}  # 过滤缓存目录和 macOS 压缩包目录

        for current_root, dir_names, _ in os.walk(self.scripts_root_dir):
            # 原地过滤，阻止 os.walk 继续进入这些目录
            dir_names[:] = [name for name in dir_names if name not in ignored_dir_names]

            directories.add(os.path.abspath(current_root))
            for dir_name in dir_names:
                directories.add(os.path.abspath(os.path.join(current_root, dir_name)))

        return [self._build_directory_item(path) for path in sorted(directories)]

    def get_catalog(self) -> dict:
        return {
            'items': self.list_scripts(),
            'directories': self.list_directories(),
        }

    def get_script_content(self, script_name: str) -> str:
        safe_name = self._normalize_script_name(script_name)
        if not safe_name:
            raise ValueError('Invalid script name')
        script_path = self._resolve_abs_path(safe_name)
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f'Script not found: {script_name}')
        with open(script_path, 'r', encoding='utf-8') as f:
            return f.read()

    def save_script(self, script_name: str, content: str) -> dict:
        safe_name = self._normalize_script_name(script_name)
        if not safe_name:
            raise ValueError('Invalid script name')
        script_path = self._resolve_abs_path(safe_name)
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {'name': safe_name[:-3], 'path': safe_name, 'size': os.path.getsize(script_path)}

    def delete_script(self, script_name: str) -> dict:
        safe_name = self._normalize_script_name(script_name)
        if not safe_name:
            raise ValueError('Invalid script name')
        script_path = self._resolve_abs_path(safe_name)
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f'Script not found: {script_name}')
        os.remove(script_path)
        return {'name': safe_name[:-3], 'path': safe_name, 'deleted': True}

    def upload_script(self, file_storage, directory: str = '') -> dict:
        if file_storage is None:
            raise ValueError('file is required')

        original_name = str(getattr(file_storage, 'filename', '') or '').strip()
        if not original_name:
            raise ValueError('filename is required')

        safe_filename = secure_filename(Path(original_name).name)
        if not safe_filename:
            raise ValueError('Invalid filename')
        if not safe_filename.lower().endswith('.py'):
            raise ValueError('Only .py files are supported')

        directory = self._normalize_directory_path(directory)
        if directory:
            safe_name = self._normalize_script_name(f'{directory}/{safe_filename}')
        else:
            safe_name = self._normalize_script_name(safe_filename)

        if not safe_name:
            raise ValueError('Invalid script name')

        script_path = self._resolve_abs_path(safe_name)
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        file_storage.save(script_path)

        return {
            'name': safe_name[:-3],
            'path': safe_name,
            'size': os.path.getsize(script_path),
        }

    def create_directory(self, directory: str) -> dict:
        safe_directory = self._normalize_directory_path(directory)
        if not safe_directory:
            raise ValueError('directory is required')
        dir_path = self._resolve_abs_path(safe_directory)
        os.makedirs(dir_path, exist_ok=True)
        return {'path': safe_directory, 'created': True}

    def rename_directory(self, directory: str, new_directory: str) -> dict:
        source_directory = self._normalize_directory_path(directory)
        target_directory = self._normalize_directory_path(new_directory)

        if not source_directory:
            raise ValueError('directory is required')
        if not target_directory:
            raise ValueError('new directory is required')

        source_path = self._resolve_abs_path(source_directory)
        target_path = self._resolve_abs_path(target_directory)

        if not os.path.isdir(source_path):
            raise FileNotFoundError(f'Directory not found: {directory}')
        if os.path.exists(target_path):
            raise FileExistsError(f'Target directory already exists: {new_directory}')

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        os.rename(source_path, target_path)

        return {
            'path': target_directory,
            'old_path': source_directory,
            'renamed': True,
        }

    def delete_directory(self, directory: str) -> dict:
        safe_directory = self._normalize_directory_path(directory)
        if not safe_directory:
            raise ValueError('directory is required')

        dir_path = self._resolve_abs_path(safe_directory)
        if not os.path.isdir(dir_path):
            raise FileNotFoundError(f'Directory not found: {directory}')

        shutil.rmtree(dir_path)

        return {
            'path': safe_directory,
            'deleted': True,
        }

    def rename_script(self, script_name: str, new_name: str) -> dict:
        safe_source_name = self._normalize_script_name(script_name)
        safe_target_name = self._normalize_script_name(new_name)
        if not safe_source_name:
            raise ValueError('script name is required')
        if not safe_target_name:
            raise ValueError('new script name is required')

        source_path = self._resolve_abs_path(safe_source_name)
        target_path = self._resolve_abs_path(safe_target_name)

        if not os.path.isfile(source_path):
            raise FileNotFoundError(f'Script not found: {script_name}')
        if os.path.exists(target_path):
            raise FileExistsError(f'Target script already exists: {new_name}')

        # Prepare the metadata change before moving the file. Only the existing
        # name literal changes; all comments, formatting and script code stay intact.
        with open(source_path, 'r', encoding='utf-8', newline='') as source:
            original = source.read()
        updated = rewrite_script_metadata_name(original, safe_target_name[:-3])
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if updated == original:
            os.rename(source_path, target_path)
        else:
            pending = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                                 dir=os.path.dirname(target_path), delete=False) as staged:
                    pending = staged.name
                    staged.write(updated)
                shutil.copymode(source_path, pending)
                os.rename(source_path, target_path)
                try:
                    os.replace(pending, target_path)
                except OSError:
                    os.rename(target_path, source_path)
                    raise
            finally:
                if pending and os.path.exists(pending):
                    os.unlink(pending)
        return {
            'name': safe_target_name[:-3],
            'path': safe_target_name,
            'old_name': safe_source_name[:-3],
            'old_path': safe_source_name,
            'renamed': True,
        }
