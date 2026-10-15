import hmac

from werkzeug.security import check_password_hash

from flask import Blueprint, current_app, redirect, request, send_from_directory

from server.config.config import (
    ADMIN_PASSWORD_HASH,
    ADMIN_USERNAME,
    WEB_AUTH_SESSION_DAYS,
)
from server.web.api_response import WebApiResponder
from server.web.auth_guard import WebAuthGuard, allow_anonymous


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
            'username': auth_guard.get_session_username() or ADMIN_USERNAME,
        })

    @blueprint.post('/api/auth/login')
    @allow_anonymous
    def auth_login():
        payload = request.get_json(silent=True) or {}
        username = str(payload.get('username') or '').strip()
        password = str(payload.get('password') or '')

        if not username:
            return responder.fail('username is required', 400)
        if not password:
            return responder.fail('password is required', 400)

        if not hmac.compare_digest(username, ADMIN_USERNAME) or not check_password_hash(ADMIN_PASSWORD_HASH, password):
            return responder.fail('Invalid username or password', 401)

        auth_guard.login_user(username)
        return responder.ok({
            'authenticated': True,
            'username': username,
            'session_days': WEB_AUTH_SESSION_DAYS,
        })

    @blueprint.post('/api/auth/logout')
    def auth_logout():
        auth_guard.logout_user()
        return responder.ok({'authenticated': False})

    return blueprint