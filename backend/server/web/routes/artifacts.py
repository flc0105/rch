import os

from flask import Blueprint, request, send_file

from server.web.api_response import WebApiResponder
from server.web.operation_id import get_optional_operation_id
from server.web.artifact_upload import save_uploaded_artifact_from_request
from server.web.auth_guard import allow_anonymous
from server.web.request_parsers import (
    get_json_payload,
    get_optional_tab_id,
)


def create_artifacts_blueprint(server_instance):
    blueprint = Blueprint('artifacts', __name__)
    web_service = server_instance.web_service
    artifact_api = web_service.artifact_api
    responder = WebApiResponder()

    @blueprint.get('/api/artifacts')
    def get_artifacts():
        artifact_type = (request.args.get('type') or '').strip()
        machine_id = (request.args.get('machine_id') or '').strip()
        filters = {key: (request.args.get(key) or '').strip() for key in ('scope', 'folder_id', 'category', 'search')}
        return responder.json_endpoint(
            lambda: artifact_api.list_artifacts(artifact_type=artifact_type, machine_id=machine_id, **filters),
            default_error_status=500,
        )

    @blueprint.post('/api/artifacts/folders')
    def create_artifact_folder():
        payload = get_json_payload()
        return responder.json_endpoint(lambda: artifact_api.create_folder(
            payload.get('scope', ''), payload.get('name', ''), payload.get('parent_id', '')))

    @blueprint.post('/api/artifacts/folders/<folder_id>/rename')
    def rename_artifact_folder(folder_id):
        payload = get_json_payload()
        return responder.json_endpoint(lambda: artifact_api.rename_folder(folder_id, payload.get('name', '')))

    @blueprint.delete('/api/artifacts/folders/<folder_id>')
    def delete_artifact_folder(folder_id):
        return responder.json_endpoint(lambda: artifact_api.delete_folder(folder_id))

    @blueprint.post('/api/artifacts/<artifact_id>/move')
    def move_artifact_folder(artifact_id):
        payload = get_json_payload()
        return responder.json_endpoint(lambda: artifact_api.move_artifact(artifact_id, payload.get('folder_id', '')))

    @blueprint.post('/api/artifacts/create')
    def create_empty_artifact():
        payload = get_json_payload()
        return responder.json_endpoint(lambda: artifact_api.create_file(
            payload.get('scope', ''), payload.get('name', ''),
            payload.get('machine_id', ''), payload.get('folder_id', '')))

    @blueprint.post('/api/artifacts/<artifact_id>/save-to-saved')
    def save_preview_to_saved(artifact_id):
        payload = get_json_payload()
        return responder.json_endpoint(lambda: artifact_api.save_preview_to_saved(
            artifact_id, payload.get('folder_id', '')))

    @blueprint.get('/api/artifacts/<artifact_id>/download')
    def download_artifact(artifact_id):
        try:
            artifact = artifact_api.get_artifact_by_id(artifact_id)
            file_path = artifact_api.get_artifact_file_path(artifact_id)
            download_name = artifact.get('original_name') or artifact.get('stored_name') or os.path.basename(file_path)
            return send_file(file_path, as_attachment=True, download_name=download_name)
        except Exception as e:
            return responder.map_common_error(e)

    @blueprint.get('/api/artifacts/<artifact_id>/raw')
    def raw_artifact(artifact_id):
        try:
            file_path = artifact_api.get_artifact_file_path(artifact_id)
            return send_file(file_path, as_attachment=False)
        except Exception as e:
            return responder.map_common_error(e)

    @blueprint.get('/api/artifacts/<artifact_id>/preview')
    def preview_artifact(artifact_id):
        return responder.file_endpoint(lambda: artifact_api.build_artifact_preview_payload(artifact_id))

    @blueprint.get('/api/artifacts/<artifact_id>/zip-peek')
    def peek_artifact_zip(artifact_id):
        return responder.file_endpoint(lambda: artifact_api.inspect_zip_artifact(artifact_id))

    @blueprint.post('/api/artifacts/<artifact_id>/zip-entry')
    def read_artifact_zip_entry(artifact_id):
        payload = get_json_payload()
        return responder.file_endpoint(
            lambda: artifact_api.read_zip_artifact_entry(artifact_id, payload.get('entry_name', '')))

    @blueprint.delete('/api/artifacts/<artifact_id>')
    def delete_artifact(artifact_id):
        return responder.file_endpoint(lambda: artifact_api.delete_artifact(artifact_id))

    @blueprint.post('/api/artifacts/<artifact_id>/rename')
    def rename_artifact(artifact_id):
        def _execute():
            payload = get_json_payload()
            new_name = (payload.get('name') or payload.get('original_name') or '').strip()
            if not new_name:
                raise ValueError('new name is required')
            return artifact_api.rename_artifact(artifact_id, new_name)
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/artifacts/clear')
    def clear_artifacts():
        def _execute():
            payload = get_json_payload()
            artifact_type = (payload.get('type') or '').strip()
            machine_id = (payload.get('machine_id') or '').strip()
            scope = (payload.get('scope') or '').strip()
            folder_id = (payload.get('folder_id') or '').strip()
            return artifact_api.clear_artifacts(artifact_type, machine_id=machine_id,
                                                scope=scope, folder_id=folder_id)
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/artifacts/command-output/save')
    def save_command_output_artifact():
        def _execute():
            payload = get_json_payload()

            if any(key in payload for key in ('source', 'category', 'job_name')):
                raise ValueError('Use output_kind and extra.saved_from for output saves')
            content = payload.get('content', '')
            output_kind = str(payload.get('output_kind') or 'command').strip()
            client_id = (payload.get('client_id') or '').strip()
            hostname = (payload.get('hostname') or '').strip()
            machine_id = (payload.get('machine_id') or '').strip()
            source_command = (payload.get('source_command') or '').strip()
            source_command_id = payload.get('source_command_id')
            output_format = str(payload.get('output_format') or 'text').strip().lower()
            job_id = (payload.get('job_id') or '').strip()
            job_key = (payload.get('job_key') or '').strip()
            extra = payload.get('extra') if isinstance(payload.get('extra'), dict) else {}

            return artifact_api.save_command_output_artifact(
                content=content,
                output_kind=output_kind,
                client_id=client_id,
                hostname=hostname,
                machine_id=machine_id,
                source_command=source_command,
                source_command_id=source_command_id,
                output_format=output_format,
                job_id=job_id,
                job_key=job_key,
                extra=extra,
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/files/upload')
    @allow_anonymous
    def upload_file():
        return responder.json_endpoint(
            lambda: save_uploaded_artifact_from_request(artifact_api),
            default_error_status=500,
        )


    @blueprint.post('/api/artifacts/<artifact_id>/send-to-client')
    def send_artifact_to_client(artifact_id):
        def _execute():
            payload = get_json_payload()
            client_id = (payload.get('client_id') or '').strip()
            target_path = (payload.get('target_path') or '').strip()
            if not client_id:
                raise ValueError('client_id is required')
            return artifact_api.send_artifact_to_client(
                artifact_id,
                client_id,
                target_path=target_path,
                tab_id=get_optional_tab_id(),
                conflict_policy=payload.get('conflict_policy', 'stop'),
                operation_id=get_optional_operation_id(),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.put('/api/artifacts/<artifact_id>/content')
    def update_artifact_content(artifact_id):
        def _execute():
            payload = get_json_payload()
            content = payload.get('content', '')
            encoding = (payload.get('encoding') or 'utf-8').strip()
            return artifact_api.update_artifact_content(artifact_id=artifact_id, content=content, encoding=encoding)
        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
