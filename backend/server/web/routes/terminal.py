from flask import Blueprint, request

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_terminal_blueprint(server_instance):
    blueprint = Blueprint('terminal', __name__)
    terminal_api = server_instance.web_service.terminal_api
    responder = WebApiResponder()

    @blueprint.post('/api/connections/<client_id>/pty/open')
    def open_pty(client_id):
        def _execute():
            payload = get_json_payload()
            result = terminal_api.open_pty_session(
                client_id,
                cols=payload.get('cols') or 120,
                rows=payload.get('rows') or 32,
                shell=(payload.get('shell') or '').strip(),
                cwd=(payload.get('cwd') or '').strip(),
            )
            result['ws_path'] = f"/ws/pty/{result['pty_session_id']}?token={result.get('ws_token') or ''}"
            return result

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/pty/<pty_session_id>/poll')
    def poll_pty(pty_session_id):
        def _execute():
            after_seq = int(request.args.get('after_seq') or 0)
            return terminal_api.poll_pty_session(pty_session_id, after_seq=after_seq)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/pty/<pty_session_id>/input')
    def send_pty_input(pty_session_id):
        def _execute():
            payload = get_json_payload()
            return terminal_api.send_pty_input(pty_session_id, str(payload.get('data') or ''))

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/pty/<pty_session_id>/resize')
    def resize_pty(pty_session_id):
        def _execute():
            payload = get_json_payload()
            return terminal_api.resize_pty_session(
                pty_session_id,
                cols=payload.get('cols') or 120,
                rows=payload.get('rows') or 32,
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/pty/<pty_session_id>/close')
    def close_pty(pty_session_id):
        def _execute():
            payload = get_json_payload()
            return terminal_api.close_pty_session(
                pty_session_id, user_initiated=payload.get('reason') != 'switch_shell',
                reason=payload.get('reason') or '',
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
