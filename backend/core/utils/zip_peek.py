"""Bounded, read-only ZIP preview shared by Client and Server."""
import os
import posixpath
import stat
import zipfile

from core.utils.text_encoding import decode_text_bytes


class ZipPeekService:
    PEEK_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
    PEEK_MAX_ENTRIES = 5000
    PEEK_MAX_ENTRY_BYTES = 2 * 1024 * 1024

    def __init__(self, checkpoint=None, iter_checked=None):
        self.checkpoint = checkpoint
        self.iter_checked = iter_checked

    def _checkpoint(self):
        if self.checkpoint is not None:
            self.checkpoint()

    def _iter(self, iterable, check_interval=1):
        if self.iter_checked is None:
            return iterable
        return self.iter_checked(iterable, check_interval=check_interval)

    def _require_zip_file(self, archive_path):
        path = os.fspath(archive_path)
        if not os.path.isfile(path) or not zipfile.is_zipfile(path):
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
        if os.path.getsize(path) > self.PEEK_MAX_ARCHIVE_BYTES:
            raise ValueError('ZIP exceeds archive preview byte limit')
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

            with archive.open(info) as entry:
                data = entry.read(self.PEEK_MAX_ENTRY_BYTES + 1)
            if len(data) > self.PEEK_MAX_ENTRY_BYTES:
                raise ValueError('ZIP entry exceeds preview byte limit')

        try:
            decoded, encoding = decode_text_bytes(data)
        except (UnicodeError, ValueError):
            return {
                'path': self._normalize_zip_member_name(info.filename),
                'entry_name': info.filename,
                'name': os.path.basename(self._normalize_zip_member_name(info.filename)),
                'size': int(info.file_size or 0),
                'type': 'binary',
                'content': '',
                'message': 'Binary or unsupported text encoding',
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

