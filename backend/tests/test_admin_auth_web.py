import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from server.web import auth_guard
from server.web.routes import auth as auth_routes


class AdminAuthWebTests(unittest.TestCase):
    def setUp(self):
        self.password_hash = generate_password_hash('initial-secret', method='scrypt:32768:8:1')
        self.app = Flask(__name__)
        self.app.secret_key = 'test-only-session-signing-secret'
        self.app.register_blueprint(auth_routes.create_auth_blueprint())
        self.client = self.app.test_client()
        self.overrides = [
            patch.object(auth_routes, 'ADMIN_USERNAME', 'admin'),
            patch.object(auth_routes, 'ADMIN_PASSWORD_HASH', self.password_hash),
            patch.object(auth_guard, 'ADMIN_USERNAME', 'admin'),
            patch.object(auth_guard, 'ADMIN_PASSWORD_HASH', self.password_hash),
            patch.object(auth_guard, 'ADMIN_API_TOKEN', 'unit-test-api-token-value-long-enough'),
            patch.object(auth_guard, 'WEB_SESSION_SECRET', 'unit-test-session-version-secret'),
        ]
        for override in self.overrides:
            override.start()
            self.addCleanup(override.stop)

    def test_password_verification_and_session(self):
        invalid = self.client.post('/api/auth/login', json={
            'username': 'admin', 'password': 'wrong',
        })
        self.assertEqual(invalid.status_code, 401)
        valid = self.client.post('/api/auth/login', json={
            'username': 'admin', 'password': 'initial-secret',
        })
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.json['data']['authenticated'])
        session = self.client.get('/api/auth/session')
        self.assertTrue(session.json['data']['authenticated'])

    def test_password_change_invalidates_existing_sessions_not_static_token(self):
        self.client.post('/api/auth/login', json={
            'username': 'admin', 'password': 'initial-secret',
        })
        new_hash = generate_password_hash('changed-secret', method='scrypt:32768:8:1')
        with patch.object(auth_guard, 'ADMIN_PASSWORD_HASH', new_hash):
            session = self.client.get('/api/auth/session')
            self.assertFalse(session.json['data']['authenticated'])
        with self.app.test_request_context(
            '/api/private', headers={'Authorization': 'Bearer unit-test-api-token-value-long-enough'},
        ):
            self.assertTrue(auth_guard.WebAuthGuard().has_valid_static_token())


if __name__ == '__main__':
    unittest.main()
