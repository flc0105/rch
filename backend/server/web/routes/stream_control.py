from flask import Blueprint, request

from server.application.command.control_builtin_support import HTTP_CONTROL_ACTIONS
from server.application.connection.control_command_store import (
    HTTP_CONTROL_COMMANDS,
    get_control_command_store,
)
from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous




def create_stream_control_blueprint(server_instance):
    blueprint = Blueprint('stream_control', __name__)
    web_service = server_instance.web_service
    responder = WebApiResponder()
    control_command_store = get_control_command_store()
    control_command_store.set_timeout_callback(
        lambda payload: web_service.event_bus.publish('httpctl_timeout', payload)
    )

    @blueprint.get('/api/httpctl/actions')
    def list_http_control_actions():
        return responder.json_endpoint(
            lambda: [
                {'action': action, **spec}
                for action, spec in HTTP_CONTROL_ACTIONS.items()
                if action in HTTP_CONTROL_COMMANDS
            ],
        )

    @blueprint.get('/api/connections/<client_id>/control')
    @allow_anonymous
    def get_connection_control(client_id):
        def _execute():
            command = control_command_store.pop_pending_command(client_id)
            if command:
                web_service.event_bus.publish('httpctl_consumed', command)
            return command or {'command': ''}

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/control')
    def set_connection_control(client_id):
        def _execute():
            payload = request.get_json(silent=True) or {}
            command = str(payload.get('command') or '').strip().lower()

            if command not in HTTP_CONTROL_COMMANDS:
                raise ValueError('Unsupported HTTP control action')

            # HTTP control queues commands independently of the active command slot.
            return control_command_store.set_pending_command(client_id, command)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/control/ack')
    @allow_anonymous
    def acknowledge_connection_control(client_id):
        def _execute():
            payload = request.get_json(silent=True) or {}
            outcome = control_command_store.acknowledge_control(
                client_id, str(payload.get('command_id') or ''),
                str(payload.get('status') or ''), str(payload.get('detail') or ''),
            )
            web_service.event_bus.publish('httpctl_result', {'client_id': client_id, **outcome})
            return outcome
        return responder.json_endpoint(_execute)

    return blueprint
