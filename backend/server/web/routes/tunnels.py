"""Thin HTTP endpoints for the same tunnel instance lifecycle used by CLI."""
from flask import Blueprint

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_tunnel_blueprint(server_instance):
    blueprint = Blueprint('tunnels', __name__)
    responder = WebApiResponder()

    def service():
        from tunnel.instances import instance_service_for
        return instance_service_for(server_instance)

    def remote():
        return server_instance.web_service.command_execution_api.remote_execution_service

    @blueprint.get('/api/connections/<client_id>/tunnels')
    def list_tunnels(client_id):
        return responder.json_endpoint(lambda: service().list(client_id))

    @blueprint.post('/api/connections/<client_id>/tunnels')
    def create_tunnel(client_id):
        def execute():
            payload = get_json_payload()
            return service().create(client_id, payload.get('name'), payload)
        return responder.json_endpoint(execute)

    @blueprint.put('/api/connections/<client_id>/tunnels/<name>')
    def edit_tunnel(client_id, name):
        return responder.json_endpoint(lambda: service().edit(client_id, name, get_json_payload()))

    @blueprint.delete('/api/connections/<client_id>/tunnels/<name>')
    def delete_tunnel(client_id, name):
        return responder.json_endpoint(lambda: service().remove(client_id, name))

    @blueprint.post('/api/connections/<client_id>/tunnels/<name>/<action>')
    def lifecycle_tunnel(client_id, name, action):
        if action not in ('start', 'stop', 'restart'):
            return responder.fail('Unsupported tunnel action', 404)
        return responder.json_endpoint(lambda: getattr(service(), action)(client_id, name, remote()))

    return blueprint
