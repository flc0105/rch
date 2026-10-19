import json
import os
from datetime import datetime

from core.utils.text_encoding import encode_for_existing_file


class WebArtifactApi:
    def __init__(self, server, event_bus, artifact_service, command_execution_api=None):
        self.server = server
        self.event_bus = event_bus
        self.artifact_service = artifact_service
        self.command_execution_api = command_execution_api

    def list_artifacts(self, artifact_type: str = '', machine_id: str = ''):
        return {
            'items': self.artifact_service.list_artifacts(artifact_type=artifact_type, machine_id=machine_id),
            'machines': self.artifact_service.list_artifact_machines(),
        }

    def delete_artifact(self, artifact_id: str):
        return self.artifact_service.delete_artifact(artifact_id)

    def rename_artifact(self, artifact_id: str, new_name: str):
        return self.artifact_service.rename_artifact(artifact_id, new_name)

    def clear_artifacts(self, artifact_type: str, machine_id: str = ''):
        return self.artifact_service.clear_artifacts(artifact_type, machine_id=machine_id)

    def build_artifact_preview_payload(self, artifact_id: str):
        return self.artifact_service.build_preview_payload(artifact_id)

    def get_artifact_file_path(self, artifact_id: str):
        return self.artifact_service.get_artifact_file_path(artifact_id)

    def get_artifact_by_id(self, artifact_id: str):
        return self.artifact_service.get_artifact_by_id(artifact_id)

    def publish_artifact_created(self, artifact_info: dict):
        if not isinstance(artifact_info, dict):
            return

        self.event_bus.publish('artifact_created', {
            'artifact_id': artifact_info.get('artifact_id', ''),
            'artifact_type': artifact_info.get('artifact_type', ''),
            'category': artifact_info.get('category', ''),
            'hostname': artifact_info.get('hostname', ''),
            'machine_id': artifact_info.get('machine_id', ''),
            'client_id': artifact_info.get('client_id', ''),
            'original_name': artifact_info.get('original_name', ''),
            'stored_name': artifact_info.get('stored_name', ''),
            'size': artifact_info.get('size', 0),
            'created_at': artifact_info.get('created_at', ''),
            # 'source_type': artifact_info.get('source_type', ''),
            'download_url': artifact_info.get('download_url', ''),
            'preview_url': artifact_info.get('preview_url', ''),
        })

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

    def save_http_uploaded_file(self, upload, artifact_type: str = 'files', category: str = '', client_id: str = '',
                                hostname: str = '', machine_id: str = '', job_id: str = '', job_name: str = '',
                                job_key: str = '',
                                # source_type: str = 'client_upload',
                                # related_path: str = '',
                                source_command_id=None, transfer_buffer_size=None, extra=None):
        resolved_hostname, resolved_machine_id, addr = self.resolve_client_context(client_id)
        hostname = hostname or resolved_hostname
        machine_id = machine_id or resolved_machine_id
        artifact = self.artifact_service.save_http_uploaded_file(
            upload,
            artifact_type=artifact_type,
            category=category,
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
                                     extra=None):
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
        )


    def send_artifact_to_client(self, artifact_id: str, client_id: str, target_path: str = '', tab_id: str = ''):
        if self.command_execution_api is None:
            raise RuntimeError('command_execution_api is not available')

        artifact = self.get_artifact_by_id(artifact_id)
        if artifact.get('artifact_type') != 'shared_files':
            raise ValueError('Only shared files can be sent to client')
        file_path = self.get_artifact_file_path(artifact_id)
        display_name = (artifact.get('original_name') or artifact.get('stored_name') or os.path.basename(file_path)).strip()
        if not display_name:
            raise ValueError('display_name is required')

        task_info = self.command_execution_api.submit_web_upload(
            client_id,
            file_path,
            display_name,
            remote_path=target_path,
            tab_id=tab_id,
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
        preview_type = self.artifact_service.guess_preview_type(artifact.get('original_name', ''))
        if preview_type != 'text':
            raise ValueError('Only text files can be edited')
        with open(file_path, 'rb') as f:
            original_bytes = f.read()
        encoded_bytes = encode_for_existing_file(content, encoding, original_bytes)
        with open(file_path, 'wb') as f:
            f.write(encoded_bytes)
        file_size = os.path.getsize(file_path)
        meta_path = artifact.get('_meta_path', '')
        if meta_path and os.path.isfile(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                meta['size'] = file_size
                meta['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        return {'artifact_id': artifact_id, 'size': file_size, 'encoding': encoding, 'message': 'File updated successfully'}
