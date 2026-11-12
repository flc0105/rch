import os

from core.utils.text_encoding import encode_for_existing_file
from core.artifact_contract import (
    ArtifactType,
)
from server.application.artifact.artifact_events import publish_artifact_created


class WebArtifactApi:
    def __init__(self, server, event_bus, artifact_service, command_execution_api=None, background_job_store=None):
        self.server = server
        self.event_bus = event_bus
        self.artifact_service = artifact_service
        self.command_execution_api = command_execution_api
        self.background_job_store = background_job_store

    def _project_job_links(self, artifacts):
        if not self.background_job_store:
            return artifacts
        links = self.background_job_store.artifact_job_links([row.get('artifact_id') for row in artifacts])
        return [dict(row, linked_jobs=links[row['artifact_id']]) if row['artifact_id'] in links else row
                for row in artifacts]

    @staticmethod
    def _list_item(artifact: dict) -> dict:
        """Explicit list response: no internal path diagnostics or extra payload."""
        fields = ('artifact_id', 'artifact_type', 'folder_id', 'original_name',
                  'stored_name', 'size', 'category', 'machine_id', 'saved_at',
                  'is_available', 'download_url', 'raw_url', 'preview_url')
        return {key: artifact[key] for key in fields if key in artifact}

    def list_artifacts(self, artifact_type: str = '', machine_id: str = '', **filters):
        artifacts = self.artifact_service.list_artifacts(
            artifact_type=artifact_type, machine_id=machine_id, **filters)
        return {
            'items': [self._list_item(item) for item in artifacts],
            'folders': self.artifact_service.list_folders(),
            'machines': self.artifact_service.list_artifact_machines(),
        }

    def delete_artifact(self, artifact_id: str):
        return self.artifact_service.delete_artifact(artifact_id)

    def rename_artifact(self, artifact_id: str, new_name: str):
        return self.artifact_service.rename_artifact(artifact_id, new_name)

    def clear_artifacts(self, artifact_type: str = '', machine_id: str = '', **filters):
        return self.artifact_service.clear_artifacts(artifact_type, machine_id=machine_id, **filters)

    def create_folder(self, artifact_type, name, parent_id=''):
        return self.artifact_service.create_folder(artifact_type, name, parent_id)

    def rename_folder(self, folder_id, name):
        return self.artifact_service.rename_folder(folder_id, name)

    def delete_folder(self, folder_id):
        return self.artifact_service.delete_folder(folder_id)

    def move_artifact(self, artifact_id, folder_id):
        return self.artifact_service.move_artifact(artifact_id, folder_id)

    def save_preview_to_saved(self, artifact_id: str, folder_id: str = ''):
        artifact = self.artifact_service.save_preview_to_saved(artifact_id, folder_id)
        self.publish_artifact_created(artifact)
        return artifact

    def create_file(self, artifact_type: str, name: str, machine_id: str = '', folder_id: str = ''):
        if artifact_type != ArtifactType.SHARED.value:
            raise ValueError('Create File is only available in Shared Files')
        name = os.path.basename(str(name or '').strip())
        if not name or name in ('.', '..'):
            raise ValueError('Invalid file name')
        if folder_id:
            folder = self.artifact_service.registry_service.catalog.get_folder(folder_id)
            if folder['artifact_type'] != artifact_type:
                raise ValueError('Folder does not belong to this file space')
        artifact = self.artifact_service.save_text_artifact(
            artifact_type=ArtifactType.SHARED.value,
            category='', hostname='', machine_id=machine_id,
            original_name=name, content='',
        )
        if folder_id:
            artifact = self.artifact_service.move_artifact(artifact['artifact_id'], folder_id)
        self.publish_artifact_created(artifact)
        return artifact

    def build_artifact_preview_payload(self, artifact_id: str):
        return self.artifact_service.build_preview_payload(artifact_id)

    def inspect_zip_artifact(self, artifact_id: str):
        return self.artifact_service.inspect_zip_artifact(artifact_id)

    def read_zip_artifact_entry(self, artifact_id: str, entry_name: str):
        return self.artifact_service.read_zip_artifact_entry(artifact_id, entry_name)

    def get_artifact_file_path(self, artifact_id: str):
        return self.artifact_service.get_artifact_file_path(artifact_id)

    def get_artifact_by_id(self, artifact_id: str):
        artifact = self.artifact_service.get_artifact_by_id(artifact_id)
        return self._project_job_links([artifact])[0] if artifact else None

    def publish_artifact_created(self, artifact_info: dict):
        publish_artifact_created(self.event_bus, artifact_info)

    def resolve_client_context(self, client_id: str) -> tuple[str, str, str]:
        hostname = ''
        machine_id = ''
        addr = ''
        if not client_id:
            return hostname, machine_id, addr
        try:
            conn = self.server.get_target_connection_by_client_id(client_id)
            conn_info = getattr(conn, 'session_info', None)
            hostname = getattr(conn_info, 'hostname', '') or ''
            machine_id = getattr(conn_info, 'machine_id', '') or ''
            addr = getattr(conn_info, 'addr', '') or ''
        except Exception:
            pass
        return hostname, machine_id, addr

    def create_upload_temp_file(self, upload):
        return self.artifact_service.create_upload_temp_file(upload)

    def create_upload_temp_path(self, filename: str):
        return self.artifact_service.create_upload_temp_path(filename)

    def cleanup_upload_temp_file(self, temp_path: str):
        self.artifact_service.cleanup_upload_temp_file(temp_path)

    def get_upload_temp_file_path(self, temp_id: str, filename: str):
        return self.artifact_service.get_upload_temp_file_path(temp_id, filename)

    def save_http_uploaded_file(self, upload, artifact_type: str = ArtifactType.SAVED.value, client_id: str = '',
                                hostname: str = '', machine_id: str = '', job_id: str = '', source_command_id=None, transfer_buffer_size=None, extra=None,
                                category: str | None = None, folder_id: str = '', folder: str = ''):
        expected_type = ArtifactType(artifact_type)
        if expected_type == ArtifactType.SAVED:
            if folder or folder_id:
                raise ValueError('Saved Files uploads use category, not folder')
        else:
            if category is not None:
                raise ValueError('Only Saved Files can have category')
            if expected_type == ArtifactType.PREVIEW and (folder or folder_id):
                raise ValueError('Preview cache does not support folders')
            if folder and folder_id:
                raise ValueError('Specify folder or folder_id, not both')
            if folder:
                folder_id = self.artifact_service.registry_service.catalog.resolve_folder(
                    expected_type.value, folder)
            if folder_id:
                folder_info = self.artifact_service.registry_service.catalog.get_folder(folder_id)
                if folder_info['artifact_type'] != expected_type.value:
                    raise ValueError('Folder does not belong to this file space')
        resolved_hostname, resolved_machine_id, addr = self.resolve_client_context(client_id)
        artifact = self.artifact_service.save_http_uploaded_file(
            upload,
            artifact_type=artifact_type,
            category=category or '',
            client_id=client_id,
            hostname=hostname or resolved_hostname,
            machine_id=machine_id or resolved_machine_id,
            source_command_id=source_command_id,
            addr=addr,
            transfer_buffer_size=transfer_buffer_size,
            extra=extra,
            folder_id=folder_id,
        )
        if job_id and self.background_job_store and self.background_job_store.get_job_for_scope(job_id):
            self.background_job_store.link_artifact(job_id, artifact)
        try:
            self.publish_artifact_created(artifact)
        except Exception:
            pass
        return artifact


    def allocate_command_output_artifact_path(self, *, output_kind: str, machine_id: str, source_command: str) -> dict:
        return self.artifact_service.allocate_command_output_artifact_path(
            output_kind=output_kind, machine_id=machine_id, source_command=source_command,
        )

    def register_command_output_artifact(self, *, allocation: dict, output_kind: str, hostname: str, machine_id: str,
                                         client_id: str = '', addr: str = '', source_command: str = '',
                                         source_command_id=None, extra=None) -> dict:
        artifact = self.artifact_service.register_command_output_artifact(
            allocation=allocation, output_kind=output_kind, hostname=hostname, machine_id=machine_id,
            client_id=client_id, addr=addr, source_command=source_command,
            source_command_id=source_command_id, extra=extra if isinstance(extra, dict) else {},
        )
        try:
            self.publish_artifact_created(artifact)
        except Exception:
            pass
        return artifact

    def save_command_output_artifact(self, *, content: str, output_kind: str = 'command',
                                     client_id: str = '', hostname: str = '', machine_id: str = '',
                                     source_command: str = '', source_command_id=None,
                                     job_id: str = '', job_key: str = '', extra=None, output_format: str = 'text'):
        resolved_hostname, resolved_machine_id, addr = self.resolve_client_context(client_id)
        if job_id and (not self.background_job_store or not self.background_job_store.get_job_for_scope(
                job_id, machine_id=machine_id or resolved_machine_id)):
            raise ValueError('Background job not found in this machine')
        artifact = self.artifact_service.save_command_output_artifact(
            content=content, output_kind=output_kind, client_id=client_id,
            hostname=hostname or resolved_hostname, machine_id=machine_id or resolved_machine_id,
            source_command=source_command, source_command_id=source_command_id,
            addr=addr, job_key=job_key,
            extra=extra if isinstance(extra, dict) else {}, output_format=output_format,
        )
        if job_id:
            self.background_job_store.link_artifact(job_id, artifact)
        return artifact


    def send_artifact_to_client(self, artifact_id: str, client_id: str, target_path: str = '', tab_id: str = '', conflict_policy='stop', operation_id: str = ''):
        if self.command_execution_api is None:
            raise RuntimeError('command_execution_api is not available')

        artifact = self.get_artifact_by_id(artifact_id)
        if artifact.get('artifact_type') != ArtifactType.SHARED.value:
            raise ValueError('Only shared files can be sent to client')
        file_path = self.get_artifact_file_path(artifact_id)
        display_name = (artifact.get('original_name') or artifact.get('stored_name') or os.path.basename(file_path)).strip()
        if not display_name:
            raise ValueError('display_name is required')

        if conflict_policy not in ('stop', 'replace', 'keep_both'):
            raise ValueError('Invalid upload conflict policy')

        task_info = self.command_execution_api.submit_web_upload(
            client_id,
            file_path,
            display_name,
            remote_path=target_path,
            tab_id=tab_id,
            conflict_policy=conflict_policy,
            operation_id=operation_id,
        )
        return {
            **task_info,
            'artifact_id': artifact.get('artifact_id', artifact_id),
            'original_name': artifact.get('original_name', ''),
            'stored_name': artifact.get('stored_name', ''),
        }

    def update_artifact_content(self, artifact_id: str, content: str, encoding: str = 'utf-8'):
        if content is None:
            raise ValueError('content is required')
        artifact = self.get_artifact_by_id(artifact_id)
        if not artifact:
            raise FileNotFoundError('Artifact not found')
        file_path = self.get_artifact_file_path(artifact_id)
        if not file_path or not os.path.isfile(file_path):
            raise FileNotFoundError('Artifact file not found')
        with open(file_path, 'rb') as f:
            original_bytes = f.read()
        if len(original_bytes) > self.artifact_service.MAX_PREVIEW_TEXT_BYTES:
            raise ValueError('Truncated text files cannot be edited')
        encoded_bytes = encode_for_existing_file(content, encoding, original_bytes)
        with open(file_path, 'wb') as f:
            f.write(encoded_bytes)
        file_size = os.path.getsize(file_path)
        self.artifact_service.update_artifact_size(artifact_id)
        return {'artifact_id': artifact_id, 'size': file_size, 'encoding': encoding, 'message': 'File updated successfully'}
