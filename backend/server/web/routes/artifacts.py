import os

from flask import Blueprint, request, send_file

from server.web.api_response import WebApiResponder
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
        return responder.json_endpoint(
            lambda: artifact_api.list_artifacts(artifact_type=artifact_type, machine_id=machine_id),
            default_error_status=500,
        )

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
            if not artifact_type:
                raise ValueError('type is required')
            return artifact_api.clear_artifacts(artifact_type, machine_id=machine_id)
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/artifacts/command-output/save')
    def save_command_output_artifact():
        def _execute():
            payload = get_json_payload()

            content = payload.get('content', '')
            category = (payload.get('category') or 'command_output').strip()
            client_id = (payload.get('client_id') or '').strip()
            hostname = (payload.get('hostname') or '').strip()
            machine_id = (payload.get('machine_id') or '').strip()
            source = (payload.get('source') or '').strip()
            source_command = (payload.get('source_command') or '').strip()
            source_command_id = payload.get('source_command_id')
            job_id = (payload.get('job_id') or '').strip()
            job_name = (payload.get('job_name') or '').strip()
            job_key = (payload.get('job_key') or '').strip()
            extra = payload.get('extra') if isinstance(payload.get('extra'), dict) else {}

            return artifact_api.save_command_output_artifact(
                content=content,
                category=category,
                client_id=client_id,
                hostname=hostname,
                machine_id=machine_id,
                source=source,
                source_command=source_command,
                source_command_id=source_command_id,
                job_id=job_id,
                job_name=job_name,
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
