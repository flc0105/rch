import os

from core.utils.text_encoding import encode_for_existing_file
from core.artifact_contract import (
    ArtifactScope, ArtifactType, ArtifactSourceKind, scope_for_type, SAVED_SOURCE_BY_FOLDER_ID, classify_artifact,
)
from server.application.artifact.artifact_events import publish_artifact_created


class WebArtifactApi:
    def __init__(self, server, event_bus, artifact_service, command_execution_api=None):
        self.server = server
        self.event_bus = event_bus
        self.artifact_service = artifact_service
        self.command_execution_api = command_execution_api

    def list_artifacts(self, artifact_type: str = '', machine_id: str = '', **filters):
        return {
            'items': self.artifact_service.list_artifacts(artifact_type=artifact_type, machine_id=machine_id, **filters),
            'folders': self.artifact_service.list_folders(),
            'machines': self.artifact_service.list_artifact_machines(),
        }

    def delete_artifact(self, artifact_id: str):
        return self.artifact_service.delete_artifact(artifact_id)

    def rename_artifact(self, artifact_id: str, new_name: str):
        return self.artifact_service.rename_artifact(artifact_id, new_name)

    def clear_artifacts(self, artifact_type: str = '', machine_id: str = '', **filters):
        return self.artifact_service.clear_artifacts(artifact_type, machine_id=machine_id, **filters)

    def create_folder(self, scope, name, parent_id=''):
        return self.artifact_service.create_folder(scope, name, parent_id)

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

    def create_file(self, scope: str, name: str, machine_id: str = '', folder_id: str = ''):
        if scope != ArtifactScope.SHARED.value:
            raise ValueError('Create File is only available in Shared Files')
        name = os.path.basename(str(name or '').strip())
        if not name or name in ('.', '..'):
            raise ValueError('Invalid file name')
        if folder_id:
            folder = self.artifact_service.registry_service.catalog.get_folder(folder_id)
            if folder['scope'] != scope:
                raise ValueError('Folder does not belong to this file space')
        artifact = self.artifact_service.save_text_artifact(
            artifact_type=ArtifactType.SHARED_FILES.value,
            category='manual', hostname='', machine_id=machine_id,
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
        return self.artifact_service.get_artifact_by_id(artifact_id)

    def publish_artifact_created(self, artifact_info: dict):
        publish_artifact_created(self.event_bus, artifact_info)

    def bind_uploaded_artifact_to_history(self, client_id: str, source_command_id, artifact: dict) -> bool:
        if not client_id or source_command_id is None:
            return False
        if not isinstance(artifact, dict) or not artifact:
            return False
        try:
            session = self.server.get_target_connection_by_client_id(client_id)
        except Exception:
            return False
        return bool(self.server.command_history_orchestrator.bind_uploaded_artifact(session, source_command_id, artifact))

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

    def save_http_uploaded_file(self, upload, artifact_type: str = ArtifactType.FILES.value, category: str = '', source_kind: str = '', client_id: str = '',
                                hostname: str = '', machine_id: str = '', job_id: str = '', job_name: str = '',
                                job_key: str = '',
                                # source_type: str = 'client_upload',
                                # related_path: str = '',
                                source_command_id=None, transfer_buffer_size=None, extra=None, folder_id: str = '',
                                folder: str = ''):
        if source_kind and category:
            raise ValueError('Specify source_kind or category, not both')
        # Resolve explicit folder names before receiving any file bytes.
        if folder and folder_id:
            raise ValueError('Specify folder or folder_id, not both')
        expected_scope = scope_for_type(artifact_type)
        if folder:
            folder_id = self.artifact_service.registry_service.catalog.resolve_folder(
                expected_scope.value, folder)
        # Reject invalid destinations before creating physical files or catalog rows.
        if folder_id:
            folder_info = self.artifact_service.registry_service.catalog.get_folder(folder_id)
            if folder_info['scope'] != expected_scope.value:
                raise ValueError('Folder does not belong to this file space')
            if expected_scope == ArtifactScope.SAVED and folder_id not in SAVED_SOURCE_BY_FOLDER_ID:
                raise ValueError('Unknown Saved Files folder')
            if expected_scope == ArtifactScope.PREVIEW:
                raise ValueError('Preview cache does not support folders')
        # Validate classification before writing upload bytes; an explicit Saved
        # folder overrides the producer hint as the single source classification.
        if expected_scope == ArtifactScope.SAVED and not folder_id:
            producer_hint = source_kind or category
            if job_id and producer_hint.strip().lower() in ('', 'default'):
                producer_hint = ArtifactSourceKind.JOB_FILE.value
            classify_artifact(artifact_type, producer_hint, extra)
        resolved_hostname, resolved_machine_id, addr = self.resolve_client_context(client_id)
        hostname = hostname or resolved_hostname
        machine_id = machine_id or resolved_machine_id
        artifact = self.artifact_service.save_http_uploaded_file(
            upload,
            artifact_type=artifact_type,
            category=(source_kind or category),
            client_id=client_id,
            hostname=hostname,
            machine_id=machine_id,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            # source_type=source_type,
            source_command_id=source_command_id,
            addr=addr,
            # related_path=related_path,
            transfer_buffer_size=transfer_buffer_size,
            extra=extra,
            folder_id=folder_id,
        )
        try:
            self.bind_uploaded_artifact_to_history(client_id, source_command_id, artifact)
        except Exception:
            pass
        try:
            self.publish_artifact_created(artifact)
        except Exception:
            pass
        return artifact


    def allocate_command_output_artifact_path(self, *, category: str, machine_id: str, source_command: str) -> dict:
        return self.artifact_service.allocate_command_output_artifact_path(
            category=category,
            machine_id=machine_id,
            source_command=source_command,
        )

    def register_command_output_artifact(self, *, allocation: dict, category: str, hostname: str, machine_id: str,
                                         client_id: str = '', addr: str = '', source: str = '',
                                         source_command: str = '', source_command_id=None, extra=None) -> dict:
        artifact = self.artifact_service.register_command_output_artifact(
            allocation=allocation,
            category=category,
            hostname=hostname,
            machine_id=machine_id,
            client_id=client_id,
            addr=addr,
            source=source,
            source_command=source_command,
            source_command_id=source_command_id,
            extra=extra if isinstance(extra, dict) else {},
        )
        try:
            self.publish_artifact_created(artifact)
        except Exception:
            pass
        return artifact


    def save_command_output_artifact(self, *, content: str, category: str = 'command_output',
                                     client_id: str = '', hostname: str = '', machine_id: str = '',
                                     source: str = '', source_command: str = '', source_command_id=None,
                                     job_id: str = '', job_name: str = '', job_key: str = '',
                                     extra=None, output_format: str = 'text'):
        resolved_hostname, resolved_machine_id, addr = self.resolve_client_context(client_id)
        hostname = hostname or resolved_hostname
        machine_id = machine_id or resolved_machine_id

        return self.artifact_service.save_command_output_artifact(
            content=content,
            category=category,
            client_id=client_id,
            hostname=hostname,
            machine_id=machine_id,
            source=source,
            source_command=source_command,
            source_command_id=source_command_id,
            addr=addr,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            extra=extra if isinstance(extra, dict) else {},
            output_format=output_format,
        )


    def send_artifact_to_client(self, artifact_id: str, client_id: str, target_path: str = '', tab_id: str = '', conflict_policy='stop', operation_id: str = ''):
        if self.command_execution_api is None:
            raise RuntimeError('command_execution_api is not available')

        artifact = self.get_artifact_by_id(artifact_id)
        if artifact.get('artifact_type') != ArtifactType.SHARED_FILES.value:
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
        file_path = artifact.get('saved_path', '')
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
