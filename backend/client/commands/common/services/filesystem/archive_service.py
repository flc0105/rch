import os
import posixpath
import shutil
import stat
import tempfile
import time
import zipfile

from client.commands.common.services.filesystem.path_resolver import PathResolver


class ArchiveService:
    """
    压缩包创建与解压服务。
    """

    def __init__(self, path_resolver: PathResolver, checkpoint=None, iter_checked=None):
        self.path_resolver = path_resolver
        self.checkpoint = checkpoint
        self.iter_checked = iter_checked

    def _checkpoint(self):
        if self.checkpoint is not None:
            self.checkpoint()

    def _iter(self, iterable, check_interval: int = 1):
        if self.iter_checked is None:
            return iterable
        return self.iter_checked(iterable, check_interval=check_interval)

    def create_zip_archive(self, dir_name: str) -> str:
        import pathlib

        temp_dir = tempfile.mkdtemp()
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
        temp_dir = tempfile.mkdtemp()
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

    PEEK_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
    PEEK_MAX_ENTRIES = 5000
    PEEK_MAX_ENTRY_BYTES = 2 * 1024 * 1024
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

    def _normalize_zip_member_name(self, name: str) -> str:
        raw = str(name or '').replace('\\', '/')
        if not raw:
            return ''
        if raw.startswith('/') or raw.startswith('//'):
            raise ValueError(f'Unsafe absolute ZIP entry: {name}')
        if len(raw) >= 2 and raw[1] == ':' and raw[0].isalpha():
            raise ValueError(f'Unsafe drive-qualified ZIP entry: {name}')

        normalized = posixpath.normpath(raw).lstrip('/')
        if normalized in ('', '.'):
            return ''
        parts = [part for part in normalized.split('/') if part not in ('', '.')]
        if any(part == '..' for part in parts):
            raise ValueError(f'Unsafe parent traversal ZIP entry: {name}')
        return '/'.join(parts)

    def _is_zip_symlink(self, info: zipfile.ZipInfo) -> bool:
        mode = (int(info.external_attr or 0) >> 16) & 0xFFFF
        return stat.S_IFMT(mode) == stat.S_IFLNK

    def _zip_info_is_dir(self, info: zipfile.ZipInfo) -> bool:
        return bool(info.is_dir() or str(info.filename or '').endswith(('/', '\\')))

    def _build_zip_tree(self, infos: list[zipfile.ZipInfo]) -> list[dict]:
        roots = []
        nodes = {}

        def ensure_directory(parts: list[str]) -> dict | None:
            parent = None
            current_parts = []
            for part in parts:
                current_parts.append(part)
                path = '/'.join(current_parts)
                node = nodes.get(path)
                if node is None:
                    node = {
                        'name': part,
                        'path': path,
                        'entry_name': '',
                        'is_dir': True,
                        'size': 0,
                        'compressed_size': 0,
                        'children': [],
                    }
                    nodes[path] = node
                    if parent is None:
                        roots.append(node)
                    else:
                        parent['children'].append(node)
                parent = node
            return parent

        for info in infos:
            self._checkpoint()
            normalized = self._normalize_zip_member_name(info.filename)
            if not normalized:
                continue

            parts = normalized.split('/')
            is_dir = self._zip_info_is_dir(info)
            if is_dir:
                node = ensure_directory(parts)
                if node is not None:
                    node['entry_name'] = info.filename
                continue

            parent = ensure_directory(parts[:-1])
            path = normalized
            node = nodes.get(path)
            if node is None:
                node = {
                    'name': parts[-1],
                    'path': path,
                    'entry_name': info.filename,
                    'is_dir': False,
                    'size': int(info.file_size or 0),
                    'compressed_size': int(info.compress_size or 0),
                    'children': [],
                }
                nodes[path] = node
                if parent is None:
                    roots.append(node)
                else:
                    parent['children'].append(node)

        def sort_nodes(items: list[dict]):
            items.sort(key=lambda item: (not bool(item.get('is_dir')), str(item.get('name') or '').lower()))
            for item in items:
                children = item.get('children') or []
                if children:
                    sort_nodes(children)

        sort_nodes(roots)
        return roots

    def inspect_zip(self, archive_path: str) -> dict:
        path = self._require_zip_file(archive_path)
        archive_size = os.path.getsize(path)
        if archive_size > self.PEEK_MAX_ARCHIVE_BYTES:
            raise ValueError(
                f'ZIP is too large to peek: {archive_size} bytes '
                f'(limit {self.PEEK_MAX_ARCHIVE_BYTES} bytes)'
            )

        with zipfile.ZipFile(path, 'r') as archive:
            infos = archive.infolist()
            if len(infos) > self.PEEK_MAX_ENTRIES:
                raise ValueError(
                    f'ZIP has too many entries to peek: {len(infos)} '
                    f'(limit {self.PEEK_MAX_ENTRIES})'
                )

            file_count = 0
            uncompressed_size = 0
            compressed_size = 0
            encrypted_count = 0

            for info in self._iter(infos, check_interval=64):
                if not self._zip_info_is_dir(info):
                    file_count += 1
                    uncompressed_size += int(info.file_size or 0)
                    compressed_size += int(info.compress_size or 0)
                if int(info.flag_bits or 0) & 0x1:
                    encrypted_count += 1

            tree = self._build_zip_tree(infos)

            def count_directories(nodes: list[dict]) -> int:
                total = 0
                for node in nodes:
                    if node.get('is_dir'):
                        total += 1
                    total += count_directories(node.get('children') or [])
                return total

            dir_count = count_directories(tree)

        return {
            'path': path,
            'name': os.path.basename(path),
            'archive_size': archive_size,
            'entry_count': len(infos),
            'file_count': file_count,
            'dir_count': dir_count,
            'compressed_size': compressed_size,
            'uncompressed_size': uncompressed_size,
            'encrypted_count': encrypted_count,
            'tree': tree,
            'limits': {
                'archive_bytes': self.PEEK_MAX_ARCHIVE_BYTES,
                'entries': self.PEEK_MAX_ENTRIES,
                'entry_preview_bytes': self.PEEK_MAX_ENTRY_BYTES,
            },
        }

    def read_zip_text_entry(self, archive_path: str, entry_name: str) -> dict:
        path = self._require_zip_file(archive_path)
        requested = str(entry_name or '')
        if not requested:
            raise ValueError('ZIP entry is required')

        with zipfile.ZipFile(path, 'r') as archive:
            try:
                info = archive.getinfo(requested)
            except KeyError as e:
                raise FileNotFoundError(f'ZIP entry not found: {requested}') from e

            if self._zip_info_is_dir(info):
                raise IsADirectoryError(f'ZIP entry is a directory: {requested}')
            if int(info.flag_bits or 0) & 0x1:
                raise ValueError('Encrypted ZIP entries cannot be previewed')
            if int(info.file_size or 0) > self.PEEK_MAX_ENTRY_BYTES:
                raise ValueError(
                    f'ZIP entry is too large to preview: {info.file_size} bytes '
                    f'(limit {self.PEEK_MAX_ENTRY_BYTES} bytes)'
                )

            data = archive.read(info)

        if b'\x00' in data:
            return {
                'path': self._normalize_zip_member_name(info.filename),
                'entry_name': info.filename,
                'name': os.path.basename(self._normalize_zip_member_name(info.filename)),
                'size': int(info.file_size or 0),
                'type': 'binary',
                'content': '',
                'message': 'Binary file preview is not supported',
            }

        decoded = None
        encoding = ''
        for candidate in ('utf-8-sig', 'gb18030'):
            try:
                decoded = data.decode(candidate)
                encoding = candidate
                break
            except UnicodeDecodeError:
                continue

        if decoded is None:
            return {
                'path': self._normalize_zip_member_name(info.filename),
                'entry_name': info.filename,
                'name': os.path.basename(self._normalize_zip_member_name(info.filename)),
                'size': int(info.file_size or 0),
                'type': 'binary',
                'content': '',
                'message': 'File is not valid UTF-8/GB18030 text',
            }

        return {
            'path': self._normalize_zip_member_name(info.filename),
            'entry_name': info.filename,
            'name': os.path.basename(self._normalize_zip_member_name(info.filename)),
            'size': int(info.file_size or 0),
            'type': 'text',
            'encoding': encoding,
            'content': decoded,
        }

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

