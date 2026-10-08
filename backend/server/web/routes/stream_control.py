import json
import queue
from datetime import datetime

from flask import Blueprint, Response, request, stream_with_context

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
        return responder.json_endpoint(
            lambda: control_command_store.pop_pending_command(client_id) or {'command': ''},
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/control')
    def set_connection_control(client_id):
        def _execute():
            payload = request.get_json(silent=True) or {}
            command = str(payload.get('command') or '').strip().lower()

            if command not in HTTP_CONTROL_COMMANDS:
                raise ValueError('Unsupported HTTP control action')

            server_instance.get_target_connection_by_client_id(client_id)
            return control_command_store.set_pending_command(client_id, command)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/stream')
    def stream():
        tab_id = (request.args.get('tab_id') or '').strip()
        q = web_service.event_bus.subscribe(tab_id=tab_id)

        def event_stream():
            try:
                while True:
                    try:
                        item = q.get(timeout=15)
                        yield f"id: {item['id']}\n"
                        yield f"event: {item['event']}\n"
                        yield f"data: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        yield 'event: ping\n'
                        yield f"data: {json.dumps({'time': datetime.now().isoformat()}, ensure_ascii=False)}\n\n"
            finally:
                web_service.event_bus.unsubscribe(q)

        return Response(
            stream_with_context(event_stream()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
            },
        )

    return blueprint