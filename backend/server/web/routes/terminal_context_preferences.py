from flask import Blueprint, request

from server.web.api_response import WebApiResponder


def create_terminal_context_preferences_blueprint(server_instance):
    blueprint = Blueprint('terminal_context_preferences', __name__)
    preferences_api = server_instance.web_service.terminal_context_preferences_api
    responder = WebApiResponder()

    @blueprint.get('/api/terminal/context-preferences')
    def get_terminal_context_preferences():
        return responder.json_endpoint(
            preferences_api.get_preferences,
            default_error_status=500,
        )

    @blueprint.put('/api/terminal/context-preferences')
    def save_terminal_context_preferences():
        return responder.json_endpoint(
            lambda: preferences_api.save_preferences(request.get_json(silent=True) or {}),
            default_error_status=500,
        )

    return blueprint
