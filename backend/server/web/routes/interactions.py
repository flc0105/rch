"""Browser response API and restricted Client Script SDK interaction transport."""
from flask import Blueprint, g, request

from server.web.api_response import WebApiResponder


def create_interaction_blueprint(server_instance):
    bp = Blueprint('interactions', __name__)
    service = server_instance.web_service
    broker = service.interaction_broker
    responder = WebApiResponder()

    @bp.get('/api/interactions/pending')
    def pending():
        tab_id = (request.args.get('tab_id') or '').strip()
        if not tab_id:
            return responder.fail('tab_id is required', 400)
        return responder.ok({'items': broker.pending(tab_id)})

    @bp.post('/api/interactions/<interaction_id>/answer')
    def answer(interaction_id):
        def work():
            body = request.get_json(silent=True) or {}
            return broker.answer(interaction_id, approved=body.get('approved') is True, value=body.get('value'))
        return responder.json_endpoint(work)

    @bp.post('/api/interactions/client/request')
    def client_request():
        def work():
            identity = getattr(g, 'client_session_identity', None)
            if not identity:
                raise ValueError('A connected Client Session Token is required for interaction')
            client_id = identity['client_id']
            conn = server_instance.get_target_connection_by_client_id(client_id)
            if conn is not identity['session']:
                raise ValueError('Client session is no longer active')
            body = request.get_json(silent=True) or {}
            command_id = body.get('command_id')
            if type(command_id) is not int:
                raise ValueError('An active command ID is required for interaction')
            foreground = conn.get_foreground_task() or {}
            if foreground.get('command_id') != command_id:
                raise ValueError('Interaction does not match active foreground command')
            task_id = str(foreground.get('task_id') or '').strip()
            task = service.task_store.get_task(task_id)
            if not task or task.get('client_id') != client_id:
                raise ValueError('Active Web task not found')
            if not task.get('tab_id'):
                raise ValueError('Web tab is required for interaction')
            return broker.request(
                task_id=task_id, client_id=client_id, tab_id=task.get('tab_id') or '',
                kind=body.get('kind'), message=body.get('message'),
                title=body.get('title'), placeholder=body.get('placeholder'), options=body.get('options'),
                preview=body.get('preview'),
                timeout_seconds=body.get('timeout_seconds', 90),
                is_active=lambda: (conn.get_foreground_task() or {}).get('task_id') == task_id,
            )
        return responder.json_endpoint(work)

    return bp
