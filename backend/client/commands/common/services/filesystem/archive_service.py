import os
import posixpath
import shutil
import stat
import tempfile
import time
import zipfile

from core.utils.zip_peek import ZipPeekService
from client.commands.common.services.filesystem.path_resolver import PathResolver
from client.runtime.temp_workspace import get_temp_category_dir


class ArchiveService(ZipPeekService):
    """
    压缩包创建与解压服务。
    """

    def __init__(self, path_resolver: PathResolver, checkpoint=None, iter_checked=None):
        self.path_resolver = path_resolver
        super().__init__(checkpoint=checkpoint, iter_checked=iter_checked)

    def create_zip_archive(self, dir_name: str) -> str:
        import pathlib

        temp_dir = tempfile.mkdtemp(dir=get_temp_category_dir('archive_temp', private=True))
        directory = self.path_resolver.validate_directory_exists(dir_name)
        archive_name = os.path.basename(directory)
        parent_dir = pathlib.Path(directory).resolve().parent

        return shutil.make_archive(
            os.path.join(temp_dir, archive_name),
            format='zip',
            root_dir=parent_dir,
            base_dir=os.path.basename(directory)
        )

    def build_download_archive_name(self, paths: list[str], archive_name: str = '') -> str:
        custom_name = (archive_name or '').strip()
        if custom_name:
            if not custom_name.lower().endswith('.zip'):
                custom_name += '.zip'
            return custom_name

        if len(paths) == 1:
            base_name = os.path.basename(paths[0].rstrip('/\\')) or 'download'
            return f'{base_name}.zip'

        timestamp = time.strftime('%Y%m%d-%H%M%S')
        return f'bundle_{timestamp}.zip'

    def iter_directory_files(self, directory: str):
        for root, _, files in self._iter(os.walk(directory), check_interval=64):
            for filename in self._iter(files, check_interval=64):
                yield os.path.join(root, filename)

    def write_path_to_zip(self, archive: zipfile.ZipFile, path: str, used_names: set[str]):
        normalized_path = os.path.abspath(path)
        top_name = os.path.basename(normalized_path.rstrip('/\\')) or 'item'
        archive_root = top_name
        suffix_index = 1

        while archive_root in used_names:
            self._checkpoint()
            archive_root = f'{top_name}_{suffix_index}'
            suffix_index += 1

        used_names.add(archive_root)

        if os.path.isfile(normalized_path):
            archive.write(normalized_path, arcname=archive_root)
            return

        if os.path.isdir(normalized_path):
            has_content = False

            for file_path in self.iter_directory_files(normalized_path):
                has_content = True
                relative_path = os.path.relpath(file_path, normalized_path)
                archive.write(file_path, arcname=os.path.join(archive_root, relative_path))

            if not has_content:
                directory_entry = archive_root.rstrip('/\\') + '/'
                archive.writestr(directory_entry, '')
            return

        raise FileNotFoundError(f'Path not found: {normalized_path}')

    def create_zip_from_paths(self, paths: list[str], archive_name: str = '') -> str:
        final_name = self.build_download_archive_name(paths, archive_name=archive_name)
        temp_dir = tempfile.mkdtemp(dir=get_temp_category_dir('archive_temp', private=True))
        archive_path = os.path.join(temp_dir, final_name)

        try:
            used_names = set()
            with zipfile.ZipFile(archive_path, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
                for path in self._iter(paths, check_interval=64):
                    self.write_path_to_zip(archive, path, used_names)
            return archive_path
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def extract_archive_to_cwd(self, archive_path: str):
        shutil.unpack_archive(archive_path, os.getcwd())

    EXTRACT_MAX_ENTRIES = 50000
    EXTRACT_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024

    def normalize_zip_archive_name(self, archive_name: str, fallback: str = 'archive.zip') -> str:
        name = os.path.basename(str(archive_name or '').strip())
        if not name:
            name = fallback
        if not name.lower().endswith('.zip'):
            name += '.zip'
        if name in ('.zip', '..zip'):
            raise ValueError('Invalid ZIP archive name')
        return name

    def create_zip_in_directory(self, paths: list[str], destination_dir: str, archive_name: str = '') -> str:
        destination = self.path_resolver.validate_directory_exists(destination_dir)
        fallback = self.build_download_archive_name(paths)
        final_name = self.normalize_zip_archive_name(archive_name, fallback=fallback)
        archive_path = os.path.join(destination, final_name)

        if os.path.exists(archive_path):
            raise FileExistsError(f'Target ZIP already exists: {archive_path}')

        used_names = set()
        try:
            with zipfile.ZipFile(archive_path, mode='w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for path in self._iter(paths, check_interval=64):
                    self.write_path_to_zip(archive, path, used_names)
            return archive_path
        except Exception:
            try:
                if os.path.isfile(archive_path):
                    os.remove(archive_path)
            except Exception:
                pass
            raise

    def _require_zip_file(self, archive_path: str) -> str:
        path = self.path_resolver.validate_file_exists(archive_path)
        if not zipfile.is_zipfile(path):
            raise ValueError(f'Not a valid ZIP archive: {path}')
        return path

    def _validate_extract_infos(self, infos: list[zipfile.ZipInfo]) -> list[tuple[zipfile.ZipInfo, str]]:
        if len(infos) > self.EXTRACT_MAX_ENTRIES:
            raise ValueError(
                f'ZIP has too many entries to extract: {len(infos)} '
                f'(limit {self.EXTRACT_MAX_ENTRIES})'
            )

        total_uncompressed = sum(int(info.file_size or 0) for info in infos if not self._zip_info_is_dir(info))
        if total_uncompressed > self.EXTRACT_MAX_UNCOMPRESSED_BYTES:
            raise ValueError(
                f'ZIP expands to too much data: {total_uncompressed} bytes '
                f'(limit {self.EXTRACT_MAX_UNCOMPRESSED_BYTES} bytes)'
            )

        validated = []
        for info in self._iter(infos, check_interval=64):
            normalized = self._normalize_zip_member_name(info.filename)
            if not normalized:
                continue
            if self._is_zip_symlink(info):
                raise ValueError(f'Symlink ZIP entry is not allowed: {info.filename}')
            validated.append((info, normalized))
        return validated

    def _detect_single_root_directory(self, validated: list[tuple[zipfile.ZipInfo, str]]) -> str:
        if not validated:
            return ''

        top_names = {normalized.split('/', 1)[0] for _, normalized in validated}
        if len(top_names) != 1:
            return ''

        root_name = next(iter(top_names))
        has_root_directory = any(
            normalized == root_name and self._zip_info_is_dir(info)
            for info, normalized in validated
        )
        has_nested_entry = any(normalized.startswith(root_name + '/') for _, normalized in validated)
        has_root_file = any(
            normalized == root_name and not self._zip_info_is_dir(info)
            for info, normalized in validated
        )

        if has_root_file:
            return ''
        return root_name if has_root_directory or has_nested_entry else ''

    def _unique_extract_directory(self, destination_dir: str, base_name: str) -> str:
        clean_name = str(base_name or '').strip() or 'archive'
        candidate = os.path.join(destination_dir, clean_name)
        index = 1
        while os.path.exists(candidate):
            self._checkpoint()
            candidate = os.path.join(destination_dir, f'{clean_name}_{index}')
            index += 1
        return candidate

    def extract_zip_smart(self, archive_path: str, destination_dir: str) -> dict:
        path = self._require_zip_file(archive_path)
        destination = self.path_resolver.validate_directory_exists(destination_dir)

        with zipfile.ZipFile(path, 'r') as archive:
            validated = self._validate_extract_infos(archive.infolist())
            if not validated:
                raise ValueError('ZIP archive is empty')

            root_name = self._detect_single_root_directory(validated)
            if root_name:
                extract_base = destination
                final_path = os.path.join(destination, root_name)
                if os.path.exists(final_path):
                    raise FileExistsError(f'Extract target already exists: {final_path}')
                cleanup_path = final_path
                mode = 'single_root'
            else:
                archive_stem = os.path.splitext(os.path.basename(path))[0] or 'archive'
                extract_base = self._unique_extract_directory(destination, archive_stem)
                final_path = extract_base
                cleanup_path = extract_base
                mode = 'wrapper'

            os.makedirs(extract_base, exist_ok=True)
            extracted_files = 0
            extracted_dirs = 0

            try:
                base_real = os.path.realpath(extract_base)
                for info, normalized in validated:
                    self._checkpoint()
                    target_path = os.path.realpath(os.path.join(extract_base, *normalized.split('/')))
                    if os.path.commonpath([base_real, target_path]) != base_real:
                        raise ValueError(f'Unsafe ZIP extraction path: {info.filename}')

                    if self._zip_info_is_dir(info):
                        os.makedirs(target_path, exist_ok=True)
                        extracted_dirs += 1
                        continue

                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with archive.open(info, 'r') as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                    extracted_files += 1
            except Exception:
                try:
                    if os.path.isdir(cleanup_path):
                        shutil.rmtree(cleanup_path)
                except Exception:
                    pass
                raise

        return {
            'archive_path': path,
            'destination_dir': destination,
            'extracted_to': final_path,
            'mode': mode,
            'root_name': root_name,
            'file_count': extracted_files,
            'dir_count': extracted_dirs,
        }

