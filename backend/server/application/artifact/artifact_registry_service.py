import os
import shutil
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from werkzeug.utils import secure_filename

from core import transfer_settings
from core.artifact_contract import (
    ArtifactType, ArtifactCategory, SAVED_CATEGORY_BY_FOLDER_ID,
    normalize_saved_category, saved_category_for_folder,
)
from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog


class ArtifactRegistryService:
    """Artifact 登记、物理文件分配与查询。"""

    DEFAULT_TRANSFER_BUFFER_SIZE = transfer_settings.DEFAULT_HTTP_TRANSFER_BUFFER_SIZE
    MIN_TRANSFER_BUFFER_SIZE = transfer_settings.MIN_HTTP_TRANSFER_BUFFER_SIZE
    MAX_TRANSFER_BUFFER_SIZE = transfer_settings.MAX_HTTP_TRANSFER_BUFFER_SIZE

    ARTIFACT_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

    TYPE_SAVED = ArtifactType.SAVED.value
    TYPE_PREVIEW = ArtifactType.PREVIEW.value
    TYPE_SHARED = ArtifactType.SHARED.value
    FORMAL_TYPES = frozenset(item.value for item in ArtifactType)

    def __init__(self, artifact_service):
        self.artifact_service = artifact_service
        self._lock = threading.RLock()
        self._cleanup_preview_ids = set()
        self.catalog = ArtifactSqliteCatalog(self.artifact_service.database, self.artifact_service.artifacts_root_dir)

    def _now_text(self) -> str:
        return datetime.now().strftime(self.ARTIFACT_TIME_FORMAT)

    def _normalize_machine_id(self, machine_id: str) -> str:
        safe_name = secure_filename((machine_id or '').strip())
        return safe_name or 'unknown_machine'

    def _normalize_artifact_type(self, artifact_type: str) -> str:
        normalized = (artifact_type or '').strip()
        if normalized not in self.FORMAL_TYPES:
            raise ValueError(f'Unsupported artifact type: {artifact_type}')
        return normalized

    def allocate_artifact_path(self, artifact_type: str, machine_id: str, original_name: str) -> dict:
        normalized_type = self._normalize_artifact_type(artifact_type)
        # Artifact ID is the sole physical identity, independent of the display name.
        while True:
            artifact_id = uuid.uuid4().hex
            relative = self.catalog.object_relative_path(artifact_id)
            target_path = os.path.join(self.artifact_service.artifacts_root_dir, *relative.parts)
            if not os.path.lexists(target_path):
                break
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        return {
            'artifact_id': artifact_id,
            'artifact_type': normalized_type,
            'machine_id': '' if normalized_type == self.TYPE_SHARED else self._normalize_machine_id(machine_id),
            'original_name': original_name,
            'stored_name': artifact_id,
            'file_path': target_path,
        }

    def _build_artifact_urls(self, artifact_id: str) -> dict:
        return {
            'download_url': f'/api/artifacts/{artifact_id}/download',
            'raw_url': f'/api/artifacts/{artifact_id}/raw',
            'preview_url': f'/api/artifacts/{artifact_id}/preview',
        }

    def _build_meta_payload(self, *, artifact_id: str, artifact_type: str, hostname: str, machine_id: str,
                            original_name: str, file_path: str, size: int,
                            source_command_id=None, client_id: str = '', addr: str = '',
                            extra: dict | None = None) -> dict:
        payload = {
            'artifact_id': artifact_id,
            'artifact_type': self._normalize_artifact_type(artifact_type),
            'machine_id': machine_id,
            'client_id': client_id,
            'original_name': original_name,
            'saved_path': file_path,
            'size': int(size or 0),
            'saved_at': self._now_text(),
            'source_command_id': source_command_id,
        }
        if isinstance(extra, dict):
            # The saved timestamp and Job association have one authoritative home.
            # Do not admit a second time source or retired provenance aliases.
            retired = {'saved_at', 'created_at', 'source', 'origin', 'source_kind',
                       'clipboard_kind', 'job_id', 'job_name', 'job_key'} & extra.keys()
            if retired:
                raise ValueError('Unsupported Artifact extra fields: ' + ', '.join(sorted(retired)))
            payload['extra'] = dict(extra)
        return payload

    def _safe_remove_file(self, path: str):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def _finalize_registered_artifact(self, *, artifact_type: str, category: str, hostname: str, machine_id: str,
                                      original_name: str, file_path: str, artifact_id: str,
                                      source_command_id=None, client_id: str = '', addr: str = '',
                                      extra: dict | None = None, folder_id: str = '') -> dict:
        expected_path = self.catalog.physical_path(self.catalog.object_relative_path(artifact_id).as_posix())
        if os.path.realpath(file_path) != expected_path:
            raise ValueError('Artifact file path must match artifact_id')
        file_size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
        meta = self._build_meta_payload(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            hostname=hostname,
            machine_id=machine_id,
            original_name=original_name,
            file_path=file_path,
            size=file_size,
            source_command_id=source_command_id,
            client_id=client_id,
            addr=addr,
            extra=extra,
        )
        artifact_kind = ArtifactType(artifact_type)
        if artifact_kind == ArtifactType.SAVED:
            normalized_category = normalize_saved_category(category)
            if folder_id:
                expected_category = SAVED_CATEGORY_BY_FOLDER_ID[folder_id]
                if category and normalized_category != expected_category:
                    raise ValueError('Saved category and folder must match')
                normalized_category = expected_category
            meta['category'] = normalized_category.value
        else:
            if category:
                raise ValueError('Only Saved Files can have category')
            if artifact_kind == ArtifactType.PREVIEW and folder_id:
                raise ValueError('Preview cache does not support folders')
            if folder_id:
                meta['folder_id'] = folder_id
        return self.catalog.save(meta)

    def register_existing_artifact(self, *, artifact_type: str, category: str, hostname: str, machine_id: str,
                                   original_name: str, file_path: str, artifact_id: str,
                                   source_command_id=None, client_id: str = '', addr: str = '',
                                   extra: dict | None = None, folder_id: str = '') -> dict:
        with self._lock:
            return self._finalize_registered_artifact(
                artifact_type=artifact_type,
                category=category,
                hostname=hostname,
                machine_id=machine_id,
                original_name=original_name,
                file_path=file_path,
                artifact_id=artifact_id,
                source_command_id=source_command_id,
                client_id=client_id,
                addr=addr,
                extra=extra,
                folder_id=folder_id,
            )

    def _normalize_transfer_buffer_size(self, value) -> int:
        try:
            normalized = int(value)
        except Exception:
            normalized = self.DEFAULT_TRANSFER_BUFFER_SIZE

        return min(
            max(normalized, self.MIN_TRANSFER_BUFFER_SIZE),
            self.MAX_TRANSFER_BUFFER_SIZE,
        )

    def shared_file_names(self):
        with self._lock:
            return self.catalog.shared_file_names()

    def save_shared_upload_file(self, upload, folder_id, policy):
        with self._lock:
            if policy == 'stop' and self.catalog.shared_file_exists(folder_id, upload.filename):
                raise ValueError(f'Destination changed: {upload.filename}')
            return self.save_http_uploaded_file(upload, artifact_type=self.TYPE_SHARED, folder_id=folder_id)

    def save_http_uploaded_file(self, file, artifact_type: str = '', category: str = '', client_id: str = '',
                                hostname: str = '', machine_id: str = '',
                                source_command_id=None, addr: str = '',
                                transfer_buffer_size=None,
                                extra: dict | None = None, folder_id: str = '') -> dict:
        normalized_type = self._normalize_artifact_type(artifact_type or self.TYPE_SAVED)
        normalized_category = (category or '').strip()
        if normalized_type == self.TYPE_SHARED:
            normalized_hostname = ''
            normalized_machine_id = ''
            client_id = ''
            addr = ''
            source_command_id = None
        else:
            normalized_hostname = (hostname or '').strip() or 'unknown_host'
            normalized_machine_id = (machine_id or '').strip() or 'unknown_machine'
        allocated = self.allocate_artifact_path(
            artifact_type=normalized_type,
            machine_id=normalized_machine_id,
            original_name=file.filename,
        )
        file_path = allocated['file_path']
        buffer_size = self._normalize_transfer_buffer_size(transfer_buffer_size)
        try:
            file.save(file_path, buffer_size=buffer_size)
            return self.register_existing_artifact(
                artifact_type=normalized_type,
                category=normalized_category,
                hostname=normalized_hostname,
                machine_id=allocated['machine_id'],
                original_name=file.filename,
                file_path=file_path,
                artifact_id=allocated['artifact_id'],
                source_command_id=source_command_id,
                client_id=client_id,
                addr=addr,
                extra=extra,
                folder_id=folder_id,
            )
        except Exception:
            self._safe_remove_file(file_path)
            raise

    def save_text_artifact(self, *, artifact_type: str, category: str, hostname: str, machine_id: str,
                           original_name: str, content: str, client_id: str = '', addr: str = '',
                           source_command_id=None,
                           extra: dict | None = None) -> dict:
        normalized_type = self._normalize_artifact_type(artifact_type)
        normalized_category = (category or '').strip()

        if normalized_type == self.TYPE_SHARED:
            normalized_hostname = ''
            normalized_machine_id = ''
            client_id = ''
            addr = ''
            source_command_id = None
        else:
            normalized_hostname = (hostname or '').strip() or 'unknown_host'
            normalized_machine_id = (machine_id or '').strip() or 'unknown_machine'

        allocated = self.allocate_artifact_path(
            artifact_type=normalized_type,
            machine_id=normalized_machine_id,
            original_name=original_name,
        )

        file_path = allocated['file_path']
        with open(file_path, 'w', encoding='utf-8', errors='replace') as file_obj:
            file_obj.write('' if content is None else str(content))

        try:
            return self.register_existing_artifact(
                artifact_type=normalized_type,
                category=normalized_category,
                hostname=normalized_hostname,
                machine_id=allocated['machine_id'],
                original_name=original_name,
                file_path=file_path,
                artifact_id=allocated['artifact_id'],
                source_command_id=source_command_id,
                client_id=client_id,
                addr=addr,
                extra=extra,
            )
        except Exception:
            self._safe_remove_file(file_path)
            raise


    def _normalize_meta_for_view(self, payload: dict) -> dict:
        item = dict(payload)
        item['is_available'] = os.path.isfile(self.catalog.physical_path(item['saved_path']))
        return item

    def list_artifacts(self, artifact_type: str = '', machine_id: str = '', *,
                       folder_id: str = '', category: str = '', search: str = '') -> list[dict]:
        if artifact_type:
            self._normalize_artifact_type(artifact_type)
        with self._lock:
            items = self.catalog.list(
                artifact_type=artifact_type,
                folder_id=folder_id, machine_id=self._normalize_machine_id(machine_id) if machine_id else '',
                category=category, search=search,
            )
            return [self._normalize_meta_for_view(item) for item in items]

    def save_preview_to_saved(self, artifact_id: str, folder_id: str = '') -> dict:
        with self._lock:
            preview = self.get_artifact_by_id(artifact_id)
            if preview.get('artifact_type') != ArtifactType.PREVIEW.value:
                raise ValueError('Only preview cache can be saved to Saved Files')
            if folder_id and folder_id not in SAVED_CATEGORY_BY_FOLDER_ID:
                raise ValueError('Target folder must belong to Saved Files')
            source_path = self.get_artifact_file_path(artifact_id)
            allocated = self.allocate_artifact_path(self.TYPE_SAVED, preview.get('machine_id', ''),
                                                     preview.get('original_name', 'preview'))
            shutil.copyfile(source_path, allocated['file_path'])
            try:
                created = self.register_existing_artifact(
                    artifact_type=self.TYPE_SAVED,
                    category=(saved_category_for_folder(folder_id).value if folder_id else ArtifactCategory.DOWNLOADS.value),
                    hostname='', machine_id=preview.get('machine_id', ''),
                    client_id=preview.get('client_id', ''), addr='',
                    original_name=preview.get('original_name', 'preview'),
                    file_path=allocated['file_path'], artifact_id=allocated['artifact_id'],
                    extra={'saved_from': 'remote_file_preview'},
                    folder_id=folder_id,
                )
                return created
            except Exception:
                self._safe_remove_file(allocated['file_path'])
                raise

    def list_artifact_machines(self) -> list[dict]:
        machines = {str(row.get('machine_id') or '').strip() for row in self.catalog.list(artifact_type='saved')}
        return [{'machine_id': key, 'hostname': ''} for key in sorted(machines) if key]

    def get_artifact_by_id(self, artifact_id: str) -> dict:
        payload = self.catalog.get((artifact_id or '').strip())
        if not payload:
            raise FileNotFoundError('artifact not found')
        return self._normalize_meta_for_view(payload)

    def get_artifact_file_path(self, artifact_id: str) -> str:
        with self._lock:
            file_path = self.catalog.physical_path(self.get_artifact_by_id(artifact_id)['saved_path'])
            if not os.path.isfile(file_path):
                raise FileNotFoundError('file not found')
            # A prior-instance preview opened in this process is no longer residue.
            self._cleanup_preview_ids.discard(artifact_id)
            return file_path

    def startup_preview_entries(self):
        with self._lock:
            entries = [(row, str(Path(self.artifact_service.artifacts_root_dir).absolute() / self.catalog.object_relative_path(row['artifact_id'])))
                       for row in self.list_artifacts(artifact_type=self.TYPE_PREVIEW)
                       if row['is_available']]
            self._cleanup_preview_ids = {row['artifact_id'] for row, _ in entries}
            return entries

    def is_cleanup_preview(self, artifact_id):
        with self._lock:
            return artifact_id in self._cleanup_preview_ids

    def maintenance_residue_paths(self, kind):
        """Enumerate only canonical object-store files and TCP staging names."""
        if kind not in ('orphan', 'tcp'):
            raise ValueError('Invalid residue kind')
        with self._lock:
            ids = self.catalog.object_ids()
            root = Path(self.artifact_service.artifacts_root_dir).absolute() / 'objects'
            if not root.exists():
                return []
            if root.resolve() != root:
                raise ValueError('Unsafe Artifact root')
            paths = []
            for shard in root.iterdir():
                if (shard.is_symlink() or not shard.is_dir() or len(shard.name) != 2
                        or any(c not in '0123456789abcdef' for c in shard.name)):
                    continue
                for path in shard.iterdir():
                    if path.is_symlink() or not path.is_file():
                        continue
                    if kind == 'tcp' and path.name.startswith('.rch-transfer-'):
                        paths.append(str(path))
                    elif kind == 'orphan' and path.name not in ids:
                        try:
                            relative = self.catalog.object_relative_path(path.name)
                        except ValueError:
                            continue
                        if relative == path.relative_to(root.parent):
                            paths.append(str(path))
            return paths

    def is_orphan_artifact_path(self, path):
        with self._lock:
            root = Path(self.artifact_service.artifacts_root_dir).absolute()
            path = Path(path).absolute()
            try:
                return (path.resolve() == path and root / self.catalog.object_relative_path(path.name) == path
                        and not self.catalog.has_object_id(path.name))
            except ValueError:
                return False

    def delete_orphan_for_cleanup(self, path, remove):
        with self._lock:
            if not self.is_orphan_artifact_path(path):
                raise ValueError('Artifact is registered or path is unsafe')
            remove()

    def missing_artifact_count(self):
        with self._lock:
            count = 0
            for key in self.catalog.object_ids():
                try:
                    path = self.catalog.physical_path(self.catalog.object_relative_path(key).as_posix())
                    count += not os.path.isfile(path)
                except ValueError:
                    count += 1
            return count

    def delete_preview_for_cleanup(self, artifact_id, saved_at, unchanged):
        with self._lock:
            artifact = self.get_artifact_by_id(artifact_id)
            if (artifact_id not in self._cleanup_preview_ids or artifact['artifact_type'] != self.TYPE_PREVIEW
                    or artifact['saved_at'] != saved_at or not unchanged()):
                raise ValueError('Preview changed')
            path = Path(self.artifact_service.artifacts_root_dir).absolute() / self.catalog.object_relative_path(artifact_id)
            if path.resolve() != path:
                raise ValueError('Unsafe preview path')
            path.unlink()
            self.catalog.delete(artifact_id)
            self._cleanup_preview_ids.discard(artifact_id)

    def delete_artifact(self, artifact_id: str) -> dict:
        with self._lock:
            artifact = self.get_artifact_by_id(artifact_id)
            artifact_id = artifact['artifact_id']
            path = self.catalog.storage_root / self.catalog.object_relative_path(artifact_id)
            if path.resolve() != path:
                raise ValueError('Unsafe Artifact storage path')
            path.unlink(missing_ok=True)
            self.catalog.delete(artifact_id)
            self._cleanup_preview_ids.discard(artifact_id)
            return {
                'artifact_id': artifact_id,
                'stored_name': artifact.get('stored_name', ''),
                'saved_path': artifact.get('saved_path', ''),
            }

    def rename_artifact(self, artifact_id: str, new_name: str) -> dict:
        display_name = (new_name or '').strip()
        # This changes only a display name, not the physical storage filename.
        # Preserve Unicode names; reject path separators and control characters.
        if (not display_name or display_name in ('.', '..') or len(display_name) > 255
                or any(char in '/\\' or unicodedata.category(char) in ('Cc', 'Cs') for char in display_name)):
            raise ValueError('new name is invalid')
        with self._lock:
            artifact = self.get_artifact_by_id(artifact_id)
            if artifact['artifact_type'] == 'preview':
                raise ValueError('previews cannot be renamed')
            if not artifact['is_available']:
                raise FileNotFoundError('file not found')
            artifact['original_name'] = display_name
            # A display rename is a metadata update: no physical file moves, stable URLs.
            return self._normalize_meta_for_view(self.catalog.save(artifact))

    def update_artifact_size(self, artifact_id: str):
        with self._lock:
            artifact = self.get_artifact_by_id(artifact_id)
            artifact['size'] = os.path.getsize(self.catalog.physical_path(artifact['saved_path']))
            return self.catalog.save(artifact)

    def prune_missing_previews(self) -> int:
        deleted = 0
        for item in self.catalog.list(artifact_type='preview'):
            if not os.path.isfile(self.catalog.physical_path(item['saved_path'])):
                self.catalog.delete(item['artifact_id'])
                deleted += 1
        return deleted

    def resolve_folder(self, artifact_type, folder):
        return self.catalog.resolve_folder(artifact_type, folder)

    def get_folder(self, folder_id):
        return self.catalog.get_folder(folder_id)

    def list_folders(self, artifact_type: str = ''):
        return self.catalog.list_folders(artifact_type)

    def create_folder(self, artifact_type: str, name: str, parent_id: str = ''):
        with self._lock:
            return self.catalog.create_folder(artifact_type, name, parent_id)

    def rename_folder(self, folder_id: str, name: str):
        with self._lock:
            return self.catalog.rename_folder(folder_id, name)

    def _delete_shared_tree(self, folder_id: str, *, include_folder: bool) -> dict:
        with self._lock:
            artifact_ids, folders = self.catalog.shared_tree(folder_id)
            if include_folder:
                folders.append(folder_id)
            deleted_count = deleted_folder_count = 0
            # Remove actual file objects through the normal deletion path before
            # removing their logical folders. Stop on failure and retain remaining rows.
            try:
                for artifact_id in artifact_ids:
                    self.delete_artifact(artifact_id)
                    deleted_count += 1
                for current in folders:
                    self.catalog.delete_folder(current)
                    deleted_folder_count += 1
            except Exception as exc:
                raise RuntimeError(f'Deleted {deleted_count} file(s) and {deleted_folder_count} folder(s); '
                                   f'cleanup incomplete: {exc}') from exc
            return {'folder_id': folder_id, 'deleted_count': deleted_count,
                    'deleted_folder_count': deleted_folder_count}

    def delete_folder(self, folder_id: str):
        if not folder_id:
            raise ValueError('Folder ID is required')
        return self._delete_shared_tree(folder_id, include_folder=True)

    def move_artifact(self, artifact_id: str, folder_id: str):
        with self._lock:
            return self._normalize_meta_for_view(self.catalog.move(artifact_id, folder_id))

    def clear_artifacts(self, artifact_type: str = '', machine_id: str = '', *, folder_id: str = '') -> dict:
        if not artifact_type:
            raise ValueError('artifact type is required')
        if artifact_type == self.TYPE_SHARED:
            if machine_id:
                raise ValueError('Shared Files does not support a device filter')
            return {'artifact_type': artifact_type, 'machine_id': machine_id,
                    **self._delete_shared_tree(folder_id, include_folder=False)}
        items = self.list_artifacts(artifact_type=artifact_type, machine_id=machine_id,
                                    folder_id=folder_id)
        deleted_count = 0
        for item in items:
            try:
                self.delete_artifact(item['artifact_id'])
                deleted_count += 1
            except Exception:
                continue
        return {'artifact_type': artifact_type, 'machine_id': machine_id,
                'folder_id': folder_id, 'deleted_count': deleted_count}
