"""Server-wide Web UI preferences; no Client configuration changes."""

from flask import Blueprint

from server.application.preferences.server_preferences import ServerPreferences
from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_server_preferences_blueprint(server_instance):
    blueprint = Blueprint('server_preferences', __name__)
    responder = WebApiResponder()
    preferences = ServerPreferences(server_instance.database)

    @blueprint.get('/api/server/preferences')
    def get_server_preferences():
        return responder.json_endpoint(preferences.read)

    @blueprint.put('/api/server/preferences')
    def save_server_preferences():
        return responder.json_endpoint(lambda: preferences.save(get_json_payload()))

    return blueprint
