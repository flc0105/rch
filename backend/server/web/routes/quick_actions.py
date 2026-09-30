from flask import Blueprint

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload, get_optional_tab_id


def create_quick_actions_blueprint(server_instance):
    blueprint = Blueprint('quick_actions', __name__)
    quick_action_api = server_instance.web_service.quick_action_api
    responder = WebApiResponder()

    @blueprint.get('/api/connections/<client_id>/quick-actions')
    def list_quick_actions(client_id):
        return responder.json_endpoint(
            lambda: quick_action_api.list_quick_actions(client_id),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/quick-actions')
    def create_quick_action(client_id):
        def _execute():
            payload = get_json_payload()
            return quick_action_api.create_quick_action(
                client_id,
                payload.get('platform'),
                payload.get('alias'),
                payload.get('command'),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.put('/api/connections/<client_id>/quick-actions')
    def update_quick_action(client_id):
        def _execute():
            payload = get_json_payload()
            return quick_action_api.update_quick_action(
                client_id,
                payload.get('original_platform'),
                payload.get('original_alias'),
                payload.get('platform'),
                payload.get('alias'),
                payload.get('command'),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/connections/<client_id>/quick-actions')
    def delete_quick_action(client_id):
        def _execute():
            payload = get_json_payload()
            return quick_action_api.delete_quick_action(
                client_id,
                payload.get('platform'),
                payload.get('alias'),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/quick-actions/execute')
    def execute_quick_action(client_id):
        def _execute():
            payload = get_json_payload()
            return quick_action_api.execute_quick_action(
                client_id,
                payload.get('platform'),
                payload.get('alias'),
                arguments=payload.get('arguments'),
                presentation=payload.get('presentation') or 'dialog',
                run_id=payload.get('run_id') or '',
                tab_id=get_optional_tab_id(),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
