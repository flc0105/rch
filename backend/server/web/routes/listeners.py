"""Authenticated listener configuration endpoints."""
from flask import Blueprint
from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_listener_blueprint(server_instance):
    blueprint = Blueprint('listeners', __name__)
    manager = server_instance.listener_manager
    responder = WebApiResponder()

    @blueprint.get('/api/listeners')
    def list_listeners():
        return responder.json_endpoint(manager.list)

    @blueprint.post('/api/listeners')
    def create_listener():
        return responder.json_endpoint(lambda: manager.create(get_json_payload()))

    @blueprint.patch('/api/listeners/<listener_id>')
    def update_listener(listener_id):
        return responder.json_endpoint(lambda: manager.set_enabled(
            listener_id, get_json_payload().get('enabled', True)))

    @blueprint.delete('/api/listeners/<listener_id>')
    def remove_listener(listener_id):
        return responder.json_endpoint(lambda: manager.remove(listener_id))

    return blueprint
