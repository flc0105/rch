import os
import posixpath
import shutil
import stat
import tempfile
import zipfile

from core.utils.zip_peek import ZipPeekService
from core.utils.artifact_naming import build_artifact_filename
from client.runtime.filesystem.path_resolver import PathResolver
from client.runtime.filesystem.conflict_policy import apply_path, describe_conflict
from client.runtime.temp_workspace import get_temp_category_dir


class ArchiveService(ZipPeekService):
    """
    压缩包创建与解压服务。
    """

    def __init__(self, path_resolver: PathResolver, checkpoint=None, iter_checked=None):
        self.path_resolver = path_resolver
        super().__init__(checkpoint=checkpoint, iter_checked=iter_checked)

    def build_download_archive_name(self, paths: list[str], archive_name: str = '') -> str:
        custom_name = (archive_name or '').strip()
        if custom_name:
            if not custom_name.lower().endswith('.zip'):
                custom_name += '.zip'
            return custom_name

        if len(paths) == 1:
            base_name = os.path.basename(paths[0].rstrip('/\\')) or 'download'
            return f'{base_name}.zip'

        return build_artifact_filename('bundle', 'zip')

    def iter_directory_files(self, directory: str, on_error=None):
        for root, _, files in self._iter(os.walk(directory, onerror=on_error), check_interval=64):
            for filename in self._iter(files, check_interval=64):
                yield os.path.join(root, filename)

    def write_path_to_zip(self, archive: zipfile.ZipFile, path: str, used_names: set[str],
                          *, on_event=None, skip_unreadable: bool = False):
        """Write a source; optional ACMD observers leave existing callers unchanged."""
        normalized_path = os.path.abspath(path)
        top_name = os.path.basename(normalized_path.rstrip('/\\')) or 'item'
        archive_root = top_name
        suffix_index = 1

        while archive_root in used_names:
            self._checkpoint()
            archive_root = f'{top_name}_{suffix_index}'
            suffix_index += 1
        used_names.add(archive_root)

        def write_file(file_path, arcname):
            # Only access-denied inputs can be skipped; never conceal other I/O errors.
            # A failed write that has already created a ZIP member is not safely skippable.
            previous_entries = len(archive.filelist)
            try:
                archive.write(file_path, arcname=arcname)
            except PermissionError as exc:
                if skip_unreadable and len(archive.filelist) == previous_entries:
                    on_event('skipped', file_path, str(exc))
                    return
                raise PermissionError(
                    f'Cannot read file while creating ZIP: {file_path} ({exc}). '
                    'Use --skip-unreadable to explicitly omit unreadable inputs.'
                ) from exc
            if on_event is not None:
                on_event('file', file_path, archive.filelist[-1].file_size)

        if os.path.isfile(normalized_path):
            write_file(normalized_path, archive_root)
            return

        if os.path.isdir(normalized_path):
            has_content = False
            walk_errors = 0

            def on_walk_error(exc):
                nonlocal walk_errors
                if skip_unreadable and isinstance(exc, PermissionError):
                    walk_errors += 1
                    on_event('skipped', exc.filename or normalized_path, str(exc))
                    return
                if isinstance(exc, PermissionError):
                    raise PermissionError(
                        f'Cannot list directory while creating ZIP: {exc.filename or normalized_path} ({exc}). '
                        'Use --skip-unreadable to explicitly omit unreadable inputs.'
                    ) from exc
                raise exc

            # os.walk silently suppresses errors by default. ACMD explicitly opts
            # into complete traversal checking; Remote Files keeps its old behavior.
            on_error = on_walk_error if on_event is not None else None
            for file_path in self.iter_directory_files(normalized_path, on_error=on_error):
                has_content = True
                relative_path = os.path.relpath(file_path, normalized_path)
                write_file(file_path, os.path.join(archive_root, relative_path))

            if not has_content and not walk_errors:
                archive.writestr(archive_root.rstrip('/\\') + '/', '')
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

    def create_zip_in_directory(self, paths: list[str], destination_dir: str, archive_name: str = '',
                                *, on_event=None, skip_unreadable: bool = False) -> str:
        destination = self.path_resolver.validate_directory_exists(destination_dir)
        fallback = self.build_download_archive_name(paths)
        final_name = self.normalize_zip_archive_name(archive_name, fallback=fallback)
        archive_path = os.path.join(destination, final_name)

        # A ZIP cannot safely contain its own output file. Applies equally to
        # ACMD and the Remote File Browser using this shared method.
        output_real = os.path.realpath(archive_path)
        for source in paths:
            if os.path.isdir(source):
                source_real = os.path.realpath(source)
                try:
                    inside_source = os.path.commonpath((source_real, output_real)) == source_real
                except ValueError:
                    inside_source = False  # Different Windows volumes cannot contain one another.
                if inside_source:
                    raise ValueError('ZIP output cannot be inside an archived directory')

        if os.path.exists(archive_path):
            raise FileExistsError(f'Target ZIP already exists: {archive_path}')

        used_names = set()
        try:
            with zipfile.ZipFile(archive_path, mode='w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for path in self._iter(paths, check_interval=64):
                    self.write_path_to_zip(archive, path, used_names,
                                           on_event=on_event, skip_unreadable=skip_unreadable)
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

    def inspect_extract_target(self, archive_path: str, destination_dir: str, entry_name: str = '') -> dict:
        """Inspect a selected ZIP root without writing any destination data."""
        path = self._require_zip_file(archive_path)
        destination = self.path_resolver.validate_directory_exists(destination_dir)
        with zipfile.ZipFile(path) as archive:
            validated = self._validate_extract_infos(archive.infolist())
            if not validated:
                raise ValueError('ZIP archive is empty')
            if entry_name:
                requested = str(entry_name).replace('\\', '/')
                if '..' in requested.split('/'):
                    raise ValueError('Unsafe ZIP entry selection')
                requested = self._normalize_zip_member_name(requested)
                files = [info for info, name in validated if name == requested and not self._zip_info_is_dir(info)]
                descendants = [name for _, name in validated if name.startswith(requested + '/')]
                if len(files) > 1 or (files and descendants):
                    raise ValueError('Ambiguous ZIP entry selection')
                kind = 'file' if files else 'directory'
                if not files and not descendants and not any(name == requested for _, name in validated):
                    raise FileNotFoundError('ZIP entry not found')
                name = requested.rsplit('/', 1)[-1]
            else:
                root = self._detect_single_root_directory(validated)
                name = root or (os.path.splitext(os.path.basename(path))[0] or 'archive')
                kind = 'directory'
        target = os.path.join(destination, name)
        # The ZIP root is virtual until the extraction is staged.
        existing = describe_conflict(path, target)
        if existing:
            from client.runtime.filesystem.conflict_policy import allowed_actions, path_kind
            existing['source_kind'] = kind
            existing['target_kind'] = path_kind(target)
            existing['allowed_actions'] = allowed_actions(kind, existing['target_kind'])
        return {'conflicts': [existing] if existing else [], 'target': target}

    def extract_zip_with_policy(self, archive_path: str, destination_dir: str,
                                entry_name: str = '', policy: str = 'stop', *, on_event=None) -> dict:
        """Use existing bounded safe extractor into a private stage, then commit by policy."""
        destination = self.path_resolver.validate_directory_exists(destination_dir)
        inspected = self.inspect_extract_target(archive_path, destination, entry_name)
        target = inspected['target']
        from client.runtime.filesystem.conflict_policy import allowed_actions, path_kind
        conflict = inspected['conflicts']
        if conflict and policy not in conflict[0]['allowed_actions']:
            raise FileExistsError(f'Invalid conflict policy for {target}')
        if conflict and policy == 'skip':
            return {'destination_dir': destination, 'extracted_to': target, 'file_count': 0,
                    'dir_count': 0, 'skipped': True}
        with tempfile.TemporaryDirectory(prefix='.rch-zip-stage-', dir=destination) as stage:
            result = (self.extract_zip_entry(archive_path, stage, entry_name, on_event=on_event)
                      if entry_name else self.extract_zip_smart(archive_path, stage, on_event=on_event))
            source = result['extracted_to']
            actual_kind = path_kind(source)
            expected_kind = 'file' if entry_name and not os.path.isdir(source) else 'directory'
            if actual_kind != expected_kind:
                raise ValueError('Extracted entry type changed unexpectedly')
            output = apply_path(source, target, 'move', policy)
        return {**result, 'destination_dir': destination, 'extracted_to': output or target,
                'skipped': output is None}

    def extract_zip_entry(self, archive_path: str, destination_dir: str, entry_name: str, *, on_event=None) -> dict:
        """Extract exactly one ZIP file or directory subtree without replacing destination files."""
        path = self._require_zip_file(archive_path)
        destination = self.path_resolver.validate_directory_exists(destination_dir)
        requested = str(entry_name or '').replace('\\', '/')
        if '..' in requested.split('/'):
            raise ValueError('Unsafe ZIP entry selection')
        requested = self._normalize_zip_member_name(requested)
        if not requested:
            raise ValueError('ZIP entry is required')

        with zipfile.ZipFile(path, 'r') as archive:
            validated = self._validate_extract_infos(archive.infolist())
            exact = [(info, name) for info, name in validated if name == requested]
            descendants = [(info, name) for info, name in validated if name.startswith(requested + '/')]
            files = [info for info, _ in exact if not self._zip_info_is_dir(info)]
            if len(files) > 1 or (files and descendants):
                raise ValueError('Ambiguous ZIP entry selection')
            is_dir = not files and (bool(exact) or bool(descendants))
            if not files and not is_dir:
                raise FileNotFoundError(f'ZIP entry not found: {requested}')
            selected = (exact + descendants) if is_dir else [next(item for item in exact if item[0] is files[0])]
            # Multiple central directory records targeting one output path are ambiguous.
            names = [name for _, name in selected]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate ZIP entry paths')

            output = os.path.join(destination, requested.rsplit('/', 1)[-1])
            if os.path.lexists(output):
                raise FileExistsError(f'Extract target already exists: {output}')
            created = False
            file_count = 0
            dir_count = 0
            try:
                if is_dir:
                    os.mkdir(output)
                    created = True
                    dir_count = 1
                for info, name in selected:
                    self._checkpoint()
                    if name == requested and is_dir:
                        continue
                    relative = name[len(requested) + 1:] if is_dir else ''
                    target = os.path.join(output, *relative.split('/')) if relative else output
                    if is_dir and os.path.commonpath([os.path.realpath(output), os.path.realpath(target)]) != os.path.realpath(output):
                        raise ValueError(f'Unsafe ZIP extraction path: {info.filename}')
                    if self._zip_info_is_dir(info):
                        os.makedirs(target, exist_ok=True)
                        dir_count += 1
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with archive.open(info) as source, open(target, 'xb') as sink:
                        created = True
                        while True:
                            self._checkpoint()
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            sink.write(chunk)
                    file_count += 1
                    if on_event is not None:
                        on_event('file', name, info.file_size)
            except Exception:
                if created:
                    if is_dir:
                        shutil.rmtree(output, ignore_errors=True)
                    else:
                        try:
                            os.unlink(output)
                        except OSError:
                            pass
                raise
        return {
            'archive_path': path, 'destination_dir': destination,
            'extracted_to': output, 'mode': 'selected_entry',
            'file_count': file_count, 'dir_count': dir_count,
        }

    def extract_zip_smart(self, archive_path: str, destination_dir: str, *, on_event=None) -> dict:
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
                    if on_event is not None:
                        on_event('file', normalized, info.file_size)
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

