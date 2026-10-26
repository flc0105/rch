"""Focused behavior tests for project module: auth."""

import base64
import unittest
from server.web.password_mask import decode_masked_password
import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from werkzeug.security import check_password_hash
from server.config.admin_auth import change_admin_password, load_admin_auth, validate_admin_password
from unittest.mock import patch
from flask import Flask
from werkzeug.security import generate_password_hash
from server.config import config as server_config
from server.web import auth_guard
from server.web.routes import auth as auth_routes


KEY = b'RCH-login-transport-mask'


def masked_payload(password, username='admin'):
    nonce = bytes(range(16))
    data = password.encode('utf-8')
    masked = bytes(c ^ KEY[i % len(KEY)] ^ nonce[i % len(nonce)] for i, c in enumerate(data))
    return {'username': username, 'masked_password': base64.b64encode(masked).decode('ascii'),
            'mask_nonce': base64.b64encode(nonce).decode('ascii')}


class PasswordMaskTests(unittest.TestCase):
    def test_utf8_round_trip(self):
        value = 'secret-密码-👍'
        self.assertEqual(decode_masked_password(masked_payload(value)), value)

    def test_plaintext_field_is_not_a_login_payload(self):
        with self.assertRaises(ValueError):
            decode_masked_password({'username': 'admin', 'password': 'secret'})

    def test_rejects_bad_encoding_and_nonce(self):
        for payload in (
            {'masked_password': '%%%%', 'mask_nonce': base64.b64encode(bytes(range(16))).decode()},
            {'masked_password': 'YQ==', 'mask_nonce': 'AAAA'},
            {'masked_password': base64.b64encode(b'x' * 4097).decode(),
             'mask_nonce': base64.b64encode(bytes(range(16))).decode()},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    decode_masked_password(payload)


class AdminAuthConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / 'runtime'
        self.runtime.mkdir()
        self.path = self.runtime / 'auth.json'

    def initialize(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            auth = load_admin_auth(str(self.path))
        return auth, output.getvalue()

    def test_first_start_creates_valid_credentials_and_prints_password_once(self):
        auth, output = self.initialize()
        password = output.split('Initial administrator password: ', 1)[1].strip()
        self.assertEqual(auth['username'], 'admin')
        self.assertTrue(check_password_hash(auth['password'], password))
        self.assertNotIn(password, self.path.read_text())
        self.assertGreaterEqual(len(auth['api_token']), 32)
        self.assertGreaterEqual(len(auth['session_secret']), 32)
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.path.read_text()), auth)

        again, second_output = self.initialize()
        self.assertEqual(again, auth)
        self.assertEqual(second_output, '')

    def test_plain_password_reset_preserves_token_and_secret(self):
        initial, output = self.initialize()
        old_password = output.split('Initial administrator password: ', 1)[1].strip()
        changed = dict(initial, password='plain:replaced-secret-password')
        self.path.write_text(json.dumps(changed), encoding='utf-8')
        updated, reset_output = self.initialize()
        self.assertEqual(reset_output, '')
        self.assertTrue(check_password_hash(updated['password'], 'replaced-secret-password'))
        self.assertFalse(check_password_hash(updated['password'], old_password))
        for key in ('api_token', 'session_secret', 'username'):
            self.assertEqual(initial[key], updated[key])
        self.assertEqual(json.loads(self.path.read_text()), updated)
        self.assertNotIn('plain:', self.path.read_text())

    def test_missing_configuration_creates_fresh_credentials(self):
        original, _ = self.initialize()
        self.path.unlink()
        regenerated, output = self.initialize()
        self.assertIn('Initial administrator password:', output)
        self.assertNotEqual(original['password'], regenerated['password'])
        self.assertNotEqual(original['api_token'], regenerated['api_token'])
        self.assertNotEqual(original['session_secret'], regenerated['session_secret'])

    def test_invalid_configuration_fails_closed(self):
        cases = ('{bad json', '{}', '{"username":"admin"}')
        for content in cases:
            with self.subTest(content=content):
                self.path.write_text(content, encoding='utf-8')
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    self.initialize()
                self.assertEqual(self.path.read_text(), content)

    def test_empty_plain_password_fails_closed(self):
        original, _ = self.initialize()
        self.path.write_text(json.dumps(dict(original, password='plain:')))
        with self.assertRaisesRegex(ValueError, 'Empty plaintext'):
            self.initialize()

    def test_other_password_formats_fail_closed(self):
        original, _ = self.initialize()
        for password in ('secret-in-clear', 'md5$abc', 'scrypt:not-valid'):
            with self.subTest(password=password):
                self.path.write_text(json.dumps(dict(original, password=password)))
                with self.assertRaisesRegex(ValueError, 'Invalid administrator password hash'):
                    self.initialize()


    def test_password_change_policy_and_atomic_update_preserve_other_credentials(self):
        initial, _ = self.initialize()
        current_password = 'current12'
        initial['password'] = generate_password_hash(current_password, method='scrypt:32768:8:1')
        self.path.write_text(json.dumps(initial), encoding='utf-8')

        for invalid in ('abc1234', 'abcdefgh', '12345678'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_admin_password(invalid)

        with self.assertRaises(PermissionError):
            change_admin_password(str(self.path), 'wrong-password', 'newpass1')

        updated = change_admin_password(str(self.path), current_password, 'newpass1')
        self.assertTrue(check_password_hash(updated['password'], 'newpass1'))
        self.assertEqual(validate_admin_password('中文ab12cd'), '中文ab12cd')
        for key in ('username', 'api_token', 'session_secret'):
            self.assertEqual(initial[key], updated[key])
        self.assertEqual(json.loads(self.path.read_text()), updated)




def _masked_password(password):
    payload = masked_payload(password, username='')
    return {
        'masked_password': payload['masked_password'],
        'mask_nonce': payload['mask_nonce'],
    }


class AdminAuthWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth_path = Path(self.temp.name) / 'auth.json'
        self.password_hash = generate_password_hash('initial-secret', method='scrypt:32768:8:1')
        self.credentials = {
            'username': 'admin',
            'password': self.password_hash,
            'api_token': 'unit-test-api-token-value-long-enough',
            'session_secret': 'unit-test-session-version-secret-long-enough',
        }
        self.auth_path.write_text(json.dumps(self.credentials), encoding='utf-8')

        self.overrides = [
            patch.object(server_config, 'AUTH_PATH', str(self.auth_path)),
            patch.object(server_config, '_AUTH', dict(self.credentials)),
            patch.object(server_config, 'ADMIN_USERNAME', self.credentials['username']),
            patch.object(server_config, 'ADMIN_PASSWORD_HASH', self.credentials['password']),
            patch.object(server_config, 'ADMIN_API_TOKEN', self.credentials['api_token']),
            patch.object(server_config, 'WEB_SESSION_SECRET', self.credentials['session_secret']),
        ]
        for override in self.overrides:
            override.start()
            self.addCleanup(override.stop)

        self.app = Flask(__name__)
        self.app.secret_key = 'test-only-session-signing-secret'
        self.app.register_blueprint(auth_routes.create_auth_blueprint())
        self.client = self.app.test_client()

    def login(self, password='initial-secret'):
        return self.client.post('/api/auth/login', json=masked_payload(password))

    def test_password_verification_and_session(self):
        invalid = self.client.post('/api/auth/login', json=masked_payload('wrong'))
        self.assertEqual(invalid.status_code, 401)
        valid = self.login()
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.json['data']['authenticated'])
        session = self.client.get('/api/auth/session')
        self.assertTrue(session.json['data']['authenticated'])
        self.assertEqual(session.json['data']['username'], 'admin')

    def test_plaintext_login_is_rejected(self):
        result = self.client.post('/api/auth/login', json={
            'username': 'admin', 'password': 'initial-secret',
        })
        self.assertEqual(result.status_code, 400)

    def test_authorization_info_requires_admin_auth_and_returns_only_useful_credentials(self):
        denied = self.client.get('/api/auth/info')
        self.assertEqual(denied.status_code, 401)

        self.login()
        result = self.client.get('/api/auth/info')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['data'], {
            'username': 'admin',
            'api_token': 'unit-test-api-token-value-long-enough',
        })
        self.assertEqual(result.headers.get('Cache-Control'), 'no-store')

    def test_password_change_reloads_hash_preserves_token_and_signs_out(self):
        self.login()
        original_token = server_config.ADMIN_API_TOKEN
        original_secret = server_config.WEB_SESSION_SECRET

        result = self.client.post('/api/auth/password', json={
            'current_password': _masked_password('initial-secret'),
            'new_password': _masked_password('newpass1'),
        })
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['data']['changed'])
        self.assertFalse(result.json['data']['authenticated'])

        stored = json.loads(self.auth_path.read_text())
        self.assertTrue(check_password_hash(stored['password'], 'newpass1'))
        self.assertEqual(stored['api_token'], original_token)
        self.assertEqual(stored['session_secret'], original_secret)
        self.assertEqual(server_config.ADMIN_PASSWORD_HASH, stored['password'])

        session = self.client.get('/api/auth/session')
        self.assertFalse(session.json['data']['authenticated'])
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login('newpass1').status_code, 200)

        with self.app.test_request_context(
            '/api/private', headers={'Authorization': f'Bearer {original_token}'},
        ):
            self.assertTrue(auth_guard.WebAuthGuard().has_valid_static_token())

    def test_password_change_rejects_wrong_current_and_policy_failures_without_logging_out(self):
        self.login()
        wrong = self.client.post('/api/auth/password', json={
            'current_password': _masked_password('wrong-current'),
            'new_password': _masked_password('newpass1'),
        })
        self.assertEqual(wrong.status_code, 403)
        self.assertTrue(self.client.get('/api/auth/session').json['data']['authenticated'])

        for invalid in ('abc1234', 'abcdefgh', '12345678'):
            with self.subTest(invalid=invalid):
                rejected = self.client.post('/api/auth/password', json={
                    'current_password': _masked_password('initial-secret'),
                    'new_password': _masked_password(invalid),
                })
                self.assertEqual(rejected.status_code, 400)
                self.assertTrue(self.client.get('/api/auth/session').json['data']['authenticated'])

