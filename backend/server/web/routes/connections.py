import hmac

from flask import Blueprint, request

from server.config.config import HIDDEN_DEVICES_PASSWORD, HIDDEN_DEVICES_REQUIRE_PASSWORD
from server.web.api_response import WebApiResponder
from server.connection.runtime.foreground_task_snapshot import build_foreground_task_snapshot


def create_connections_blueprint(server_instance):
    blueprint = Blueprint('connections', __name__)
    connection_api = server_instance.web_service.connection_api
    responder = WebApiResponder()

    @blueprint.get('/api/connections')
    def get_connections():
        return responder.ok(connection_api.get_connections_payload())

    @blueprint.get('/api/connections/<client_id>/task')
    def get_connection_task(client_id):
        return responder.json_endpoint(
            lambda: build_foreground_task_snapshot(
                server_instance.get_target_connection_by_client_id(client_id)
            ),
            default_error_status=404,
        )

    @blueprint.post('/api/connections/hidden-devices/verify')
    def verify_hidden_devices_password():
        if not HIDDEN_DEVICES_REQUIRE_PASSWORD:
            return responder.ok({'required': False, 'verified': True})

        if not HIDDEN_DEVICES_PASSWORD:
            return responder.fail('Hidden devices password is not configured', 500)

        body = request.get_json(silent=True) or {}
        password = str(body.get('password') or '')
        return responder.ok({
            'required': True,
            'verified': hmac.compare_digest(password, HIDDEN_DEVICES_PASSWORD),
        })

    @blueprint.get('/api/connections/<client_id>/revision-status')
    def get_client_revision_status(client_id):
        return responder.json_endpoint(
            lambda: connection_api.get_client_revision_status(client_id),
            default_error_status=500,
        )

    @blueprint.get('/api/machines/<machine_id>/connection-history')
    def get_machine_connection_history(machine_id):
        return responder.json_endpoint(
            lambda: connection_api.get_machine_connection_history(machine_id),
            default_error_status=500,
        )

    @blueprint.get('/api/machines/<machine_id>/connection-history/<client_id>/commands')
    def get_machine_connection_commands(machine_id, client_id):
        return responder.json_endpoint(
            lambda: connection_api.get_machine_connection_commands(
                machine_id,
                client_id,
                limit=request.args.get('limit'),
                cursor=request.args.get('cursor', ''),
            ),
            default_error_status=500,
        )

    @blueprint.get('/api/device-groups')
    def get_device_groups():
        return responder.ok(connection_api.get_device_groups())

    @blueprint.post('/api/device-groups')
    def create_device_group():
        def _execute():
            body = request.get_json(silent=True) or {}
            return connection_api.create_device_group(body.get('name'))

        return responder.json_endpoint(_execute, default_error_status=400)

    @blueprint.patch('/api/device-groups/<group_id>')
    def rename_device_group(group_id):
        def _execute():
            body = request.get_json(silent=True) or {}
            return connection_api.rename_device_group(group_id, body.get('name'))

        return responder.json_endpoint(_execute, default_error_status=400)

    @blueprint.delete('/api/device-groups/<group_id>')
    def delete_device_group(group_id):
        return responder.json_endpoint(
            lambda: connection_api.delete_device_group(group_id),
            default_error_status=400,
        )

    @blueprint.patch('/api/machines/<machine_id>/device-group')
    def assign_machine_device_group(machine_id):
        def _execute():
            body = request.get_json(silent=True) or {}
            return connection_api.assign_machine_device_group(
                machine_id,
                body.get('group_id') or '',
            )

        return responder.json_endpoint(_execute, default_error_status=400)

    @blueprint.post('/api/connections/<client_id>/kill')
    def kill_connection(client_id):
        def _execute():
            server_instance.kill_connection_by_client_id(client_id)
            return None

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.patch('/api/connections/device-view-prefs')
    def update_connection_device_view_prefs():
        def _execute():
            body = request.get_json(silent=True) or {}
            client_id = str(body.get('client_id') or '').strip()
            machine_id = str(body.get('machine_id') or '').strip()
            patch = {}

            if 'machine_alias' in body:
                patch['machine_alias'] = body.get('machine_alias')
            if 'client_hidden' in body:
                patch['client_hidden'] = bool(body.get('client_hidden'))
            if 'machine_hidden' in body:
                patch['machine_hidden'] = bool(body.get('machine_hidden'))

            return connection_api.update_connection_device_view_prefs(
                client_id=client_id,
                machine_id=machine_id,
                patch=patch,
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/connections/<client_id>')
    def remove_connection(client_id):
        def _execute():
            body = request.get_json(silent=True) or {}
            machine_id = str(body.get('machine_id') or '').strip()
            return connection_api.remove_connection(client_id, machine_id=machine_id)

        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
