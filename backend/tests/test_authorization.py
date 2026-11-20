"""Credential handling and Client API authorization."""

import base64
import json
import unittest
from types import SimpleNamespace

import pytest

from client.http.session_auth import clear_token
from client.jobs.manager import JobManager
from core.protocol.client_api_auth import CLIENT_SESSION_TOKEN_HEADER
from server.application.auth.client_api_policy import ClientApiPolicy
from server.application.auth.client_session_token_service import ClientSessionTokenService
from server.config.admin_auth import load_admin_auth
from server.web.password_mask import decode_masked_password


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


def test_invalid_admin_configuration_is_not_overwritten(tmp_path):
    auth_file = tmp_path / 'auth.json'
    for content in ('{bad json', '{}', '{"username":"admin"}'):
        auth_file.write_text(content, encoding='utf-8')
        with pytest.raises(ValueError):
            load_admin_auth(str(auth_file))
        assert auth_file.read_text(encoding='utf-8') == content


def session(client_id='client-1', machine_id='machine-1'):
    return SimpleNamespace(session_info=SimpleNamespace(client_id=client_id, machine_id=machine_id))


def test_reconnect_rotates_token_and_old_disconnect_does_not_invalidate_new_one():
    service = ClientSessionTokenService()
    old = session('same')
    old_token = service.issue(old)
    new = session('same')
    new_token = service.issue(new)
    assert service.identify(old_token) is None
    service.revoke(old)
    assert service.identify(new_token)['session'] is new
    service.revoke(new)
    assert service.identify(new_token) is None


def test_client_api_attaches_token_only_to_its_server(monkeypatch):
    from client.http.client_api import ClientApiClient
    from client.http.session_auth import set_token
    from client.runtime.sdk.context import use_script_sdk_context
    clear_token()
    set_token('connected-token')
    api = ClientApiClient(base_url='https://server.example:8085')
    try:
        assert api._build_headers('https://server.example:8085/api/keychains') == {
            CLIENT_SESSION_TOKEN_HEADER: 'connected-token',
        }
        assert api._build_headers('https://evil.example/api/keychains') == {}
        assert api._build_headers('https://server.example:8085.evil.example/api/keychains') == {}
        with use_script_sdk_context(None, {'__context__': {'client_session_token': 'subprocess-token'}}):
            assert api._build_headers('https://server.example:8085/api/keychains')[CLIENT_SESSION_TOKEN_HEADER] == 'subprocess-token'
    finally:
        clear_token()


def test_client_api_policy_is_explicit_and_exact():
    policy = ClientApiPolicy()
    assert policy.allows('GET', '/api/artifacts/a/raw')
    assert not policy.allows('GET', '/api/artifacts/a/raw/other')
    assert not policy.allows('POST', '/api/artifacts/a/raw')
    assert not policy.allows('POST', '/api/connections/x/command')


def test_subprocess_job_receives_token_through_environment_not_context_file(tmp_path, monkeypatch):
    import client.jobs.manager as module

    socket = SimpleNamespace(client_id='client-1', info={'hostname': 'host'},
                             client_session_token='connected-token')
    manager = JobManager(socket)
    job_path = tmp_path / 'sample.py'
    job_path.write_text('pass\n', encoding='utf-8')
    working = tmp_path / 'job-context'
    calls = []

    class Process:
        pid = 12345
        def wait(self):
            return 0

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    monkeypatch.setattr(manager, '_monitor_subprocess', lambda runtime: None)
    runtime = manager._start_subprocess_job(
        str(job_path), 'sample.py', 7,
        job_metadata={'name': 'sample'}, resolved_params={}, cleanup_path=str(working),
    )
    runtime.thread.join(timeout=2)
    assert calls[0][1]['env']['RCH_CHILD_SESSION_TOKEN'] == 'connected-token'
    data = json.loads((working / 'job_subprocess_context.json').read_text(encoding='utf-8'))
    assert 'client_session_token' not in data
    assert 'connected-token' not in (working / 'job_subprocess_context.json').read_text(encoding='utf-8')
