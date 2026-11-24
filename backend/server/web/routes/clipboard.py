from flask import Blueprint, request

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload, get_required_upload, get_optional_tab_id


def create_clipboard_blueprint(server_instance):
    blueprint = Blueprint('clipboard', __name__)
    clipboard_api = server_instance.web_service.clipboard_api
    responder = WebApiResponder()

    @blueprint.get('/api/connections/<client_id>/clipboard/capabilities')
    def clipboard_capabilities(client_id):
        return responder.json_endpoint(
            lambda: clipboard_api.get_capabilities(client_id),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/clipboard/get')
    def get_clipboard(client_id):
        return responder.json_endpoint(
            lambda: clipboard_api.get_clipboard(client_id, tab_id=get_optional_tab_id()),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/clipboard/set-text')
    def set_clipboard_text(client_id):
        def _execute():
            payload = get_json_payload()
            return clipboard_api.set_text(client_id, payload.get('text', ''))
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/clipboard/set-image')
    def set_clipboard_image(client_id):
        return responder.json_endpoint(
            lambda: clipboard_api.set_image(client_id, get_required_upload(), tab_id=get_optional_tab_id()),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/clipboard/set-files')
    def set_clipboard_files(client_id):
        return responder.json_endpoint(
            lambda: clipboard_api.set_files(
                client_id,
                request.files.getlist('files'),
                request.form.get('manifest', ''), tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/clipboard/set-artifact-file')
    def set_clipboard_artifact_file(client_id):
        def _execute():
            payload = get_json_payload()
            return clipboard_api.set_artifact_file(
                client_id,
                payload.get('artifact_id', ''), tab_id=get_optional_tab_id(),
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
