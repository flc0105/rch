import os

from flask import Blueprint, send_file, request

from server.web.api_response import WebApiResponder
from server.web.auth_guard import WebAuthGuard


def create_server_cleanup_blueprint(server_instance, lifecycle):
    blueprint = Blueprint('server_cleanup', __name__)
    cleanup_api = server_instance.web_service.server_cleanup_api
    responder = WebApiResponder()

    auth = WebAuthGuard()

    def admin_endpoint(callback, *, starts_work=False):
        if not auth.has_valid_static_token():
            return responder.fail('Administrator authentication required', 403)
        if starts_work and lifecycle.action is not None:
            return responder.fail('Server maintenance is already pending', 409)
        response, status = responder.json_endpoint(callback)
        response.headers['Cache-Control'] = 'no-store'
        return response, status

    @blueprint.get('/api/server-cleanup/summary')
    def summary():
        return admin_endpoint(cleanup_api.summary)

    @blueprint.post('/api/server-cleanup/preview')
    def preview():
        return admin_endpoint(cleanup_api.preview)

    @blueprint.post('/api/server-cleanup/execute')
    def execute():
        return admin_endpoint(lambda: cleanup_api.execute(request.get_json()), starts_work=True)

    @blueprint.get('/api/server-cleanup/runs/<run_id>')
    def get_run(run_id):
        return admin_endpoint(lambda: cleanup_api.get_run(run_id))

    @blueprint.post('/api/server-cleanup/runs/<run_id>/cancel')
    def cancel_run(run_id):
        return admin_endpoint(lambda: cleanup_api.cancel_run(run_id))

    @blueprint.put('/api/server-cleanup/settings')
    def save_settings():
        return admin_endpoint(lambda: cleanup_api.save_settings(request.get_json()))

    @blueprint.get('/api/server/maintenance/database')
    def database_info():
        return admin_endpoint(cleanup_api.database_info)

    @blueprint.post('/api/server/maintenance/database/optimize')
    def optimize_database():
        return admin_endpoint(cleanup_api.optimize_database, starts_work=True)

    @blueprint.get('/api/server-cleanup/runs/<run_id>/log')
    def get_cleanup_log(run_id):
        if not (auth.has_valid_session() or auth.has_valid_static_token()):
            return responder.fail('Administrator authentication required', 403)
        try:
            file_path = cleanup_api.get_log_path(run_id)
            return send_file(
                file_path,
                as_attachment=False,
                download_name=os.path.basename(file_path),
                mimetype='text/plain',
            )
        except Exception as exc:
            return responder.map_common_error(exc)

    return blueprint
