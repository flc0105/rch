import os
from server.application.artifact.artifact_preview_service import ArtifactPreviewService
from server.application.artifact.artifact_registry_service import ArtifactRegistryService
from server.application.artifact.artifact_temp_file_service import ArtifactTempFileService
from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService
from server.config.config import WEB_FILES_ROOT_DIR, WEB_PREVIEW_TEXT_MAX_BYTES


class WebArtifactService:
    MAX_PREVIEW_TEXT_BYTES = WEB_PREVIEW_TEXT_MAX_BYTES

    def __init__(self, database):
        self.database = database
        self.web_root_dir = WEB_FILES_ROOT_DIR
        self.artifacts_root_dir = os.path.join(self.web_root_dir, 'artifacts')
        self.previews_dir = os.path.join(self.artifacts_root_dir, 'previews')
        self.upload_tmp_dir = os.path.join(self.artifacts_root_dir, 'upload_tmp')

        self._prepare_dirs()
        self.registry_service = ArtifactRegistryService(self)
        self.preview_service = ArtifactPreviewService(self)
        self.temp_file_service = ArtifactTempFileService(self)
        self.command_output_service = CommandOutputArtifactService(self)

    def _prepare_dirs(self):
        os.makedirs(self.artifacts_root_dir, exist_ok=True)
        os.makedirs(self.previews_dir, exist_ok=True)
        os.makedirs(self.upload_tmp_dir, exist_ok=True)

    def allocate_artifact_path(self, artifact_type: str, machine_id: str, original_name: str) -> dict:
        return self.registry_service.allocate_artifact_path(artifact_type, machine_id, original_name)

    def register_existing_artifact(self, *, artifact_type: str, category: str, hostname: str, machine_id: str,
                                   original_name: str, file_path: str, stored_name: str,

                                   source_command_id=None, client_id: str = '', addr: str = '',
                                   job_id: str = '',
                                   job_name: str = '',
                                   job_key: str = '',
                                   extra: dict | None = None) -> dict:
        return self.registry_service.register_existing_artifact(
            artifact_type=artifact_type,
            category=category,
            hostname=hostname,
            machine_id=machine_id,
            original_name=original_name,
            file_path=file_path,
            stored_name=stored_name,
            source_command_id=source_command_id,
            client_id=client_id,
            addr=addr,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            extra=extra,
        )

    def save_http_uploaded_file(self, file, artifact_type: str = '', category: str = '', client_id: str = '',
                                hostname: str = '', machine_id: str = '', job_id: str = '', job_name: str = '',
                                job_key: str = '',
                                source_command_id=None, addr: str = '',
                                transfer_buffer_size=None,
                                extra: dict | None = None, folder_id: str = '') -> dict:
        return self.registry_service.save_http_uploaded_file(
            file,
            artifact_type=artifact_type,
            category=category,
            client_id=client_id,
            hostname=hostname,
            machine_id=machine_id,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            source_command_id=source_command_id,
            addr=addr,
            transfer_buffer_size=transfer_buffer_size,
            extra=extra,
            folder_id=folder_id,
        )

    def allocate_command_output_artifact_path(self, *, category: str, machine_id: str, source_command: str, now=None) -> dict:
        return self.command_output_service.allocate_output_path(
            category=category,
            machine_id=machine_id,
            source_command=source_command,
            now=now,
        )

    def register_command_output_artifact(self, *, allocation: dict, category: str, hostname: str, machine_id: str,
                                         client_id: str = '', addr: str = '', source: str = '',
                                         source_command: str = '', source_command_id=None,
                                         job_id: str = '', job_name: str = '', job_key: str = '',
                                         extra: dict | None = None, saved_at=None) -> dict:
        return self.command_output_service.register_output_artifact(
            allocation=allocation,
            category=category,
            hostname=hostname,
            machine_id=machine_id,
            client_id=client_id,
            addr=addr,
            source=source,
            source_command=source_command,
            source_command_id=source_command_id,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            extra=extra,
            saved_at=saved_at,
        )

    def save_command_output_artifact(self, *, content: str, category: str, hostname: str, machine_id: str,
                                     client_id: str = '', addr: str = '', source: str = '',
                                     source_command: str = '', source_command_id=None,
                                     job_id: str = '', job_name: str = '', job_key: str = '',
                                     extra: dict | None = None, output_format: str = 'text') -> dict:
        return self.command_output_service.save_text_output(
            content=content,
            category=category,
            hostname=hostname,
            machine_id=machine_id,
            client_id=client_id,
            addr=addr,
            source=source,
            source_command=source_command,
            source_command_id=source_command_id,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            extra=extra,
            output_format=output_format,
        )


    def save_text_artifact(self, *, artifact_type: str, category: str, hostname: str, machine_id: str,
                           original_name: str, content: str, client_id: str = '', addr: str = '',
                           source_command_id=None, job_id: str = '', job_name: str = '', job_key: str = '',
                           extra: dict | None = None) -> dict:
        return self.registry_service.save_text_artifact(
            artifact_type=artifact_type,
            category=category,
            hostname=hostname,
            machine_id=machine_id,
            original_name=original_name,
            content=content,
            client_id=client_id,
            addr=addr,
            source_command_id=source_command_id,
            job_id=job_id,
            job_name=job_name,
            job_key=job_key,
            extra=extra,
        )

    def list_artifacts(self, artifact_type: str = '', machine_id: str = '', **filters) -> list[dict]:
        return self.registry_service.list_artifacts(artifact_type=artifact_type, machine_id=machine_id, **filters)

    def save_preview_to_saved(self, artifact_id: str, folder_id: str = ''):
        return self.registry_service.save_preview_to_saved(artifact_id, folder_id)

    def prune_missing_previews(self):
        return self.registry_service.prune_missing_previews()

    def list_folders(self, scope: str = ''):
        return self.registry_service.list_folders(scope)

    def create_folder(self, scope: str, name: str, parent_id: str = ''):
        return self.registry_service.create_folder(scope, name, parent_id)

    def rename_folder(self, folder_id: str, name: str):
        return self.registry_service.rename_folder(folder_id, name)

    def delete_folder(self, folder_id: str):
        return self.registry_service.delete_folder(folder_id)

    def move_artifact(self, artifact_id: str, folder_id: str):
        return self.registry_service.move_artifact(artifact_id, folder_id)

    def update_artifact_size(self, artifact_id: str):
        return self.registry_service.update_artifact_size(artifact_id)

    def list_artifact_machines(self) -> list[dict]:
        return self.registry_service.list_artifact_machines()

    def get_artifact_by_id(self, artifact_id: str) -> dict:
        return self.registry_service.get_artifact_by_id(artifact_id)

    def get_artifact_file_path(self, artifact_id: str) -> str:
        return self.registry_service.get_artifact_file_path(artifact_id)

    def delete_artifact(self, artifact_id: str) -> dict:
        return self.registry_service.delete_artifact(artifact_id)

    def rename_artifact(self, artifact_id: str, new_name: str) -> dict:
        return self.registry_service.rename_artifact(artifact_id, new_name)

    def clear_artifacts(self, artifact_type: str = '', machine_id: str = '', **filters) -> dict:
        return self.registry_service.clear_artifacts(artifact_type, machine_id=machine_id, **filters)

    def guess_preview_type(self, filename: str) -> str:
        return self.preview_service.guess_preview_type(filename)

    def build_preview_payload(self, artifact_id: str) -> dict:
        return self.preview_service.build_preview_payload(artifact_id)

    def inspect_zip_artifact(self, artifact_id: str) -> dict:
        return self.preview_service.inspect_zip_artifact(artifact_id)

    def read_zip_artifact_entry(self, artifact_id: str, entry_name: str) -> dict:
        return self.preview_service.read_zip_artifact_entry(artifact_id, entry_name)

    def create_upload_temp_file(self, upload) -> tuple[str, str]:
        return self.temp_file_service.create_upload_temp_file(upload)

    def create_upload_temp_path(self, filename: str) -> tuple[str, str]:
        return self.temp_file_service.create_upload_temp_path(filename)

    def stage_local_file(self, source_path: str, display_name: str = '') -> tuple[str, str]:
        return self.temp_file_service.stage_local_file(source_path, display_name)

    def get_upload_temp_file_path(self, temp_id: str, filename: str) -> str:
        return self.temp_file_service.get_temp_file_path(temp_id, filename)

    def build_upload_temp_download_relative_url(self, temp_path: str) -> str:
        return self.temp_file_service.build_temp_download_relative_url(temp_path)

    def cleanup_upload_temp_file(self, temp_path: str):
        self.temp_file_service.cleanup_temp_file(temp_path)
