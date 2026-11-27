"""Administrator-only Web lifecycle actions for the current Server process."""

from flask import Blueprint

from server.web.api_response import WebApiResponder
from server.web.auth_guard import WebAuthGuard


def _active_work(server):
    if server.web_service.server_cleanup_api.is_busy():
        return 'Server cleanup or database optimization'
    transfer_api = server.web_service.transfer_api
    if transfer_api.list_transfers().get('active'):
        return 'file transfers'
    for connection in server.connections.all():
        if connection.get_foreground_task():
            return 'foreground tasks'
        client_id = str(getattr(connection.session_info, 'client_id', '') or '').strip()
        if client_id:
            jobs = server.web_service.job_api.list_background_jobs(client_id)
            if any(str(job.get('state') or '').lower() in ('running', 'stopping') for job in jobs):
                return 'background jobs'
    return ''


def create_server_maintenance_blueprint(server_instance, lifecycle):
    blueprint = Blueprint('server_maintenance', __name__)
    auth = WebAuthGuard()
    responder = WebApiResponder()

    def authorized():
        return auth.has_valid_static_token()

    @blueprint.get('/api/server/maintenance')
    def maintenance_status():
        if not authorized():
            return responder.fail('Administrator authentication required', 403)
        response, status = responder.ok({'instance_id': lifecycle.instance_id})
        response.headers['Cache-Control'] = 'no-store'
        return response, status

    @blueprint.post('/api/server/<action>')
    def maintenance_action(action):
        if action not in ('shutdown', 'restart'):
            return responder.fail('Unknown maintenance action', 404)
        if not authorized():
            return responder.fail('Administrator authentication required', 403)
        if lifecycle.action is not None:
            return responder.fail('Server maintenance is already pending', 409)
        try:
            busy = _active_work(server_instance)
        except Exception:
            return responder.fail('Unable to verify active Server operations', 503)
        if busy:
            return responder.fail(f'Stop active {busy} before Server maintenance', 409)
        # Atomically close cleanup admission, including the delayed startup timer.
        if not server_instance.web_service.server_cleanup_api.reserve_stop():
            return responder.fail('Server cleanup or maintenance is already pending', 409)
        if not lifecycle.reserve(action):
            return responder.fail('Server maintenance is already pending', 409)
        response, status = responder.ok({'action': action, 'accepted': True})
        response.headers['Cache-Control'] = 'no-store'
        response.call_on_close(lifecycle.activate)
        return response, status

    return blueprint
