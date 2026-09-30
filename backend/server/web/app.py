from datetime import timedelta

from flask import Flask, redirect, request

from server.config.config import (
    SESSION_COOKIE_NAME,
    WEB_AUTH_SESSION_DAYS,
    WEB_HTTP_UPLOAD_MAX_BYTES,
    WEB_SESSION_SECRET,
)
from server.web.api_response import WebApiResponder
from server.web.auth_guard import WebAuthGuard
from server.web.routes.agent import create_agent_blueprint
from server.web.routes.artifacts import create_artifacts_blueprint
from server.web.routes.auth import create_auth_blueprint
from server.web.routes.background_jobs import create_background_job_blueprint
from server.web.routes.command_execution import create_command_execution_blueprint
from server.web.routes.command_history import create_command_history_blueprint
from server.web.routes.external_tools import create_external_tool_blueprint
from server.web.routes.keychains import create_keychain_blueprint
from server.web.routes.connections import create_connections_blueprint
from server.web.routes.pinned_paths import create_pinned_path_blueprint
from server.web.routes.quick_actions import create_quick_actions_blueprint
from server.web.routes.remote_files import create_remote_files_blueprint
from server.web.routes.scripts import create_script_blueprint
from server.web.routes.stream_control import create_stream_control_blueprint
from server.web.routes.system_inspection import create_system_inspection_blueprint
from server.web.routes.terminal import create_terminal_blueprint
from server.web.routes.toolbar_preferences import create_toolbar_preferences_blueprint
from server.web.routes.notification_preferences import create_notification_preferences_blueprint
from server.web.routes.notification_history import create_notification_history_blueprint
from server.web.routes.screen_view import create_screen_view_blueprint
from server.web.routes.server_cleanup import create_server_cleanup_blueprint
from server.web.routes.clipboard import create_clipboard_blueprint
from server.web.routes.device_monitor import create_device_monitor_blueprint
from server.web.routes.device_events import create_device_events_blueprint
from server.web.routes.transfers import create_transfers_blueprint


def create_app(server_instance):
    app = Flask(__name__, static_folder='../../static', static_url_path='')
    app.config['MAX_CONTENT_LENGTH'] = WEB_HTTP_UPLOAD_MAX_BYTES
    app.config['SECRET_KEY'] = WEB_SESSION_SECRET
    app.config['SESSION_COOKIE_NAME'] = SESSION_COOKIE_NAME
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=WEB_AUTH_SESSION_DAYS)

    responder = WebApiResponder()
    auth_guard = WebAuthGuard(
        script_grant_service=getattr(server_instance.web_service, 'script_grant_service', None),
    )

    app.register_blueprint(create_auth_blueprint())
    app.register_blueprint(create_connections_blueprint(server_instance))
    app.register_blueprint(create_toolbar_preferences_blueprint(server_instance))
    app.register_blueprint(create_notification_preferences_blueprint(server_instance))
    app.register_blueprint(create_notification_history_blueprint(server_instance))
    app.register_blueprint(create_server_cleanup_blueprint(server_instance))
    app.register_blueprint(create_command_execution_blueprint(server_instance))
    app.register_blueprint(create_stream_control_blueprint(server_instance))
    app.register_blueprint(create_background_job_blueprint(server_instance))
    app.register_blueprint(create_remote_files_blueprint(server_instance))
    app.register_blueprint(create_pinned_path_blueprint(server_instance))
    app.register_blueprint(create_quick_actions_blueprint(server_instance))
    app.register_blueprint(create_system_inspection_blueprint(server_instance))
    app.register_blueprint(create_command_history_blueprint(server_instance))
    app.register_blueprint(create_external_tool_blueprint(server_instance))
    app.register_blueprint(create_artifacts_blueprint(server_instance))
    app.register_blueprint(create_keychain_blueprint(server_instance))
    app.register_blueprint(create_agent_blueprint(server_instance))
    app.register_blueprint(create_script_blueprint(server_instance))
    app.register_blueprint(create_terminal_blueprint(server_instance))
    app.register_blueprint(create_screen_view_blueprint(server_instance))
    app.register_blueprint(create_clipboard_blueprint(server_instance))
    app.register_blueprint(create_device_monitor_blueprint(server_instance))
    app.register_blueprint(create_device_events_blueprint(server_instance))
    app.register_blueprint(create_transfers_blueprint(server_instance))

    @app.before_request
    def enforce_authentication():
        if request.method == 'OPTIONS':
            return None

        if auth_guard.is_public_request():
            return None

        if auth_guard.is_authenticated():
            return None

        is_api_request = (request.path or '').startswith('/api/')
        if is_api_request:
            return responder.fail('Authentication required', 401)

        return redirect('/login.html')

    @app.errorhandler(404)
    def not_found(error):
        if (request.path or '').startswith('/api/'):
            return responder.fail(f'API route not found: {request.path}', 404)
        return error

    @app.errorhandler(405)
    def method_not_allowed(error):
        if (request.path or '').startswith('/api/'):
            return responder.fail(f'API method not allowed: {request.method} {request.path}', 405)
        return error

    @app.errorhandler(413)
    def file_too_large(_):
        return responder.fail('File is too large', 413)

    return app