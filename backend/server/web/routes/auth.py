import hmac

from werkzeug.security import check_password_hash

from flask import Blueprint, current_app, redirect, request, send_from_directory

from server.config import config as server_config
from server.config.admin_auth import change_admin_password, reset_admin_api_token
from server.web.api_response import WebApiResponder
from server.web.auth_guard import WebAuthGuard, allow_anonymous
from server.web.password_mask import decode_masked_password


def create_auth_blueprint():
    blueprint = Blueprint('auth', __name__)
    responder = WebApiResponder()
    auth_guard = WebAuthGuard()

    @blueprint.get('/')
    def index():
        if not auth_guard.is_authenticated():
            return redirect('/login.html')
        return send_from_directory(current_app.static_folder, 'index.html')

    @blueprint.get('/login.html')
    @allow_anonymous
    def login_page():
        if auth_guard.is_authenticated():
            return redirect('/')
        return send_from_directory(current_app.static_folder, 'login.html')

    @blueprint.get('/api/auth/session')
    @allow_anonymous
    def auth_session():
        return responder.ok({
            'authenticated': auth_guard.is_authenticated(),
            'username': auth_guard.get_session_username() or server_config.ADMIN_USERNAME,
        })

    @blueprint.post('/api/auth/login')
    @allow_anonymous
    def auth_login():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return responder.fail('Invalid login request', 400)
        username = str(payload.get('username') or '').strip()
        try:
            password = decode_masked_password(payload)
        except ValueError:
            return responder.fail('Invalid login request', 400)

        if not hmac.compare_digest(username, server_config.ADMIN_USERNAME) or not check_password_hash(server_config.ADMIN_PASSWORD_HASH, password):
            return responder.fail('Invalid username or password', 401)

        auth_guard.login_user(username)
        return responder.ok({
            'authenticated': True,
            'username': username,
            'session_days': server_config.WEB_AUTH_SESSION_DAYS,
        })

    @blueprint.get('/api/auth/info')
    def auth_info():
        if not (auth_guard.has_valid_session() or auth_guard.has_valid_static_token()):
            return responder.fail('Authentication required', 401)
        response, status = responder.ok({
            'username': server_config.ADMIN_USERNAME,
            'api_token': server_config.ADMIN_API_TOKEN,
        })
        response.headers['Cache-Control'] = 'no-store'
        return response, status

    @blueprint.post('/api/auth/password')
    def auth_change_password():
        if not (auth_guard.has_valid_session() or auth_guard.has_valid_static_token()):
            return responder.fail('Authentication required', 401)

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return responder.fail('Invalid password change request', 400)

        try:
            current_password = decode_masked_password(payload.get('current_password'))
            new_password = decode_masked_password(payload.get('new_password'))
        except ValueError:
            return responder.fail('Invalid password change request', 400)

        try:
            change_admin_password(server_config.AUTH_PATH, current_password, new_password)
        except PermissionError as exc:
            return responder.fail(str(exc), 403)
        except ValueError as exc:
            return responder.fail(str(exc), 400)

        server_config.reload_admin_auth()
        auth_guard.logout_user()
        return responder.ok({'changed': True, 'authenticated': False})

    @blueprint.post('/api/auth/token/reset')
    def auth_reset_token():
        if not (auth_guard.has_valid_session() or auth_guard.has_valid_static_token()):
            return responder.fail('Authentication required', 401)

        reset_admin_api_token(server_config.AUTH_PATH)
        server_config.reload_admin_auth()
        response, status = responder.ok({'api_token': server_config.ADMIN_API_TOKEN})
        response.headers['Cache-Control'] = 'no-store'
        return response, status

    @blueprint.post('/api/auth/logout')
    def auth_logout():
        auth_guard.logout_user()
        return responder.ok({'authenticated': False})

    return blueprint