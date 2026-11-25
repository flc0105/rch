"""Authenticated listener configuration endpoints."""
from flask import Blueprint, send_file
from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_listener_blueprint(server_instance):
    blueprint = Blueprint('listeners', __name__)
    manager = server_instance.listener_manager
    responder = WebApiResponder()

    @blueprint.get('/api/listeners')
    def list_listeners():
        return responder.json_endpoint(manager.list)

    @blueprint.get('/api/listener-protocols')
    def list_listener_protocols():
        return responder.json_endpoint(manager.list_protocols)

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

    @blueprint.get('/api/identities')
    def list_identities():
        return responder.json_endpoint(manager.identities.status)

    @blueprint.post('/api/identities/initialize')
    def initialize_server_identity():
        return responder.json_endpoint(manager.identities.initialize)

    @blueprint.post('/api/identities/clients')
    def create_client_identity():
        def issue():
            payload = get_json_payload()
            return manager.identities.create_client(payload.get('name'), payload.get('days', 365))
        return responder.json_endpoint(issue)

    @blueprint.post('/api/identities/clients/<identity_id>/revoke')
    def revoke_client_identity(identity_id):
        return responder.json_endpoint(lambda: manager.identities.revoke(identity_id))

    @blueprint.get('/api/identities/clients/<identity_id>/download')
    def download_client_identity(identity_id):
        # Never bundle identity secrets into public Agent or Bootstrap artifacts.
        try:
            buffer = manager.identities.download(identity_id)
            response = send_file(buffer, mimetype='application/zip', as_attachment=True,
                                 download_name=f'rch-identity-{identity_id}.zip')
            response.headers['Cache-Control'] = 'no-store'
            return response
        except ValueError as exc:
            return responder.fail(str(exc), 400)

    return blueprint
