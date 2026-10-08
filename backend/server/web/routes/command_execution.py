import os

from flask import Blueprint, request, send_file

from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous
from server.web.request_parsers import (
    get_optional_tab_id,
    get_required_command,
    get_required_upload,
    get_json_payload,
)


def create_command_execution_blueprint(server_instance):
    blueprint = Blueprint('command_execution', __name__)
    web_service = server_instance.web_service
    command_execution_api = web_service.command_execution_api
    command_catalog_api = web_service.command_catalog_api
    artifact_api = web_service.artifact_api
    transfer_api = web_service.transfer_api
    responder = WebApiResponder()

    @blueprint.post('/api/connections/<client_id>/command')
    def send_command(client_id):
        def _execute():
            return command_execution_api.submit_web_command(
                client_id,
                get_required_command(),
                tab_id=get_optional_tab_id(),
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/connections/<client_id>/watchdog')
    def get_watchdog_status(client_id):
        return responder.json_endpoint(
            lambda: command_execution_api.get_watchdog_status(client_id),
            default_error_status=500,
        )

    @blueprint.get('/api/connections/<client_id>/runtime-config')
    def get_runtime_config(client_id):
        return responder.json_endpoint(
            lambda: command_execution_api.get_runtime_config(client_id),
            default_error_status=500,
        )

    @blueprint.put('/api/connections/<client_id>/runtime-config/<key>')
    def update_runtime_config(client_id, key):
        def _execute():
            payload = get_json_payload()
            if 'value' not in payload:
                raise ValueError('value is required')
            return command_execution_api.update_runtime_config(
                client_id,
                key,
                payload.get('value'),
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/connections/<client_id>/runtime-config/<key>')
    def reset_runtime_config(client_id, key):
        return responder.json_endpoint(
            lambda: command_execution_api.reset_runtime_config(client_id, key),
            default_error_status=500,
        )

    @blueprint.post('/api/tasks/<task_id>/cancel')
    def cancel_task(task_id):
        return responder.json_endpoint(
            lambda: command_execution_api.cancel_web_task(task_id),
            default_error_status=500,
        )

    @blueprint.get('/api/connections/<client_id>/command-candidates')
    def get_command_candidates(client_id):
        return responder.json_endpoint(
            lambda: command_catalog_api.get_command_candidates(client_id),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/command-completions')
    def get_command_completions(client_id):
        def _execute():
            payload = get_json_payload()
            raw_input = str(payload.get('raw_input') or '')
            cursor_position = payload.get('cursor_position')
            max_results = payload.get('max_results') or 50
            return command_catalog_api.get_command_completions(
                client_id,
                raw_input=raw_input,
                cursor_position=cursor_position,
                max_results=max_results,
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/upload')
    def upload_file_to_client(client_id):
        def _execute():
            upload = get_required_upload()
            target_path = (request.form.get('target_path') or '').strip()
            transfer_id = (request.form.get('transfer_id') or '').strip()
            tab_id = get_optional_tab_id()

            try:
                temp_path, safe_name = artifact_api.create_upload_temp_file(upload)
                if transfer_id:
                    transfer_api.mark_browser_upload_staged(
                        transfer_id,
                        total_bytes=os.path.getsize(temp_path),
                        tab_id=tab_id,
                    )

                return command_execution_api.submit_web_upload(
                    client_id,
                    temp_path,
                    safe_name,
                    target_path,
                    tab_id=tab_id,
                    transfer_id=transfer_id,
                )
            except Exception as exc:
                if transfer_id:
                    try:
                        transfer_api.fail_upload_transfer(transfer_id, str(exc), tab_id=tab_id)
                    except Exception:
                        pass
                raise

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/upload-tmp/<temp_id>/<filename>')
    @allow_anonymous
    def download_upload_tmp_file(temp_id, filename):
        try:
            file_path = artifact_api.get_upload_temp_file_path(temp_id, filename)
            return send_file(
                file_path,
                as_attachment=True,
                download_name=os.path.basename(file_path),
            )
        except Exception as e:
            return responder.map_common_error(e)

    return blueprint