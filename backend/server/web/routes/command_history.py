from flask import Blueprint, request

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_command_history_blueprint(server_instance):
    blueprint = Blueprint('command_history', __name__)
    command_history_api = server_instance.web_service.command_history_api
    responder = WebApiResponder()

    @blueprint.get('/api/machines/<machine_id>/command-history')
    def get_command_history(machine_id):
        return responder.json_endpoint(lambda: command_history_api.get_command_history(machine_id), default_error_status=500)

    @blueprint.get('/api/machines/<machine_id>/command-history/full')
    def get_full_command_history(machine_id):
        return responder.json_endpoint(
            lambda: command_history_api.get_command_execution_history(
                machine_id,
                limit=request.args.get('limit'),
                cursor=request.args.get('cursor', ''),
                query=request.args.get('query', ''),
                kind=request.args.get('kind', ''),
                errors=str(request.args.get('errors', '')).strip().lower() in ('1', 'true'),
            ),
            default_error_status=500,
        )

    @blueprint.delete('/api/machines/<machine_id>/command-history')
    def clear_command_history(machine_id):
        return responder.json_endpoint(lambda: command_history_api.clear_command_history(machine_id), default_error_status=500)

    @blueprint.post('/api/machines/<machine_id>/command-history/pin')
    def set_command_history_pinned(machine_id):
        def _execute():
            payload = get_json_payload()
            command = (payload.get('command') or '').strip()
            if not command:
                raise ValueError('command is required')
            return command_history_api.set_command_history_pinned(machine_id, command, payload.get('is_pinned', False))

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/machines/<machine_id>/command-history/pin/move')
    def move_command_history_pinned(machine_id):
        def _execute():
            payload = get_json_payload()
            command = (payload.get('command') or '').strip()
            direction = (payload.get('direction') or '').strip().lower()
            if not command:
                raise ValueError('command is required')
            if direction not in ('up', 'down'):
                raise ValueError('direction must be up or down')
            return command_history_api.move_command_history_pinned(machine_id, command, direction)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/machines/<machine_id>/command-history/full/<entry_id>')
    def delete_command_execution_history_entry(machine_id, entry_id):
        return responder.json_endpoint(
            lambda: command_history_api.delete_command_execution_history_entry(machine_id, entry_id),
            default_error_status=500,
        )

    return blueprint