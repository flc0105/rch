from flask import Blueprint, request

from core.protocol.screen import SCREEN_DEFAULT_FPS
from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_screen_view_blueprint(server_instance):
    blueprint = Blueprint('screen_view', __name__)
    screen_view_api = server_instance.web_service.screen_view_api
    responder = WebApiResponder()

    @blueprint.post('/api/connections/<client_id>/screen-view/open')
    def open_screen_view(client_id):
        def _execute():
            payload = get_json_payload()
            result = screen_view_api.open_screen_view(
                client_id,
                fps=payload.get('fps') or SCREEN_DEFAULT_FPS,
                quality=payload.get('quality') or 60,
            )
            result['ws_path'] = (
                f"/ws/screen/{result['screen_session_id']}"
                f"?token={result.get('ws_token') or ''}"
            )
            return result

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/screen-view/<screen_session_id>/poll')
    def poll_screen_view(screen_session_id):
        def _execute():
            after_seq = int(request.args.get('after_seq') or 0)
            return screen_view_api.poll_screen_view(screen_session_id, after_seq=after_seq)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/screen-view/<screen_session_id>/config')
    def update_screen_view(screen_session_id):
        def _execute():
            payload = get_json_payload()
            return screen_view_api.update_screen_view(
                screen_session_id,
                fps=payload.get('fps'),
                quality=payload.get('quality'),
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/screen-view/<screen_session_id>/close')
    def close_screen_view(screen_session_id):
        return responder.json_endpoint(
            lambda: screen_view_api.close_screen_view(screen_session_id),
            default_error_status=500,
        )

    return blueprint
