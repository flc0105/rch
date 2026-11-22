"""Bind Web URL handoff, connection-scoped endpoint and shared child resolution."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.config.config import RUNTIME_CONFIG
from client.connection.message_dispatcher import ClientInboundMessageDispatcher
from client.http.client_api import ClientApiClient
from client.http import server_endpoint
from core.protocol.message_types import MSG_TYPE_CLIENT_SESSION_TOKEN, MSG_TYPE_SESSION_CONFIG
from server.application.connection.bind_web_endpoint import validate_web_origin
from server.application.connection.connection_service import WebConnectionService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bind_runtime(monkeypatch):
    monkeypatch.setitem(RUNTIME_CONFIG, 'connection_mode', 'bind')
    monkeypatch.setattr(server_endpoint, '_state_path', '')
    monkeypatch.delenv('RCH_SERVER_WEB_ENDPOINT_STATE', raising=False)
    server_endpoint.prepare_session_endpoint()
    try:
        yield
    finally:
        server_endpoint.clear_session_base_url()
        monkeypatch.delenv('RCH_SERVER_WEB_ENDPOINT_STATE', raising=False)
        monkeypatch.setattr(server_endpoint, '_state_path', '')


def test_client_api_tracks_bind_session_and_child_process(bind_runtime):
    api = ClientApiClient()
    with pytest.raises(RuntimeError, match='until the Bind session'):
        api.build_url('/api/jobs/list')

    connection = SimpleNamespace(client_session_token='')
    dispatcher = ClientInboundMessageDispatcher(connection)
    dispatcher.dispatch({'type': MSG_TYPE_CLIENT_SESSION_TOKEN, 'token': 'session-test'})
    dispatcher.dispatch({'type': MSG_TYPE_SESSION_CONFIG, 'server_web_base_url': 'http://lan-host:8010'})
    assert api.base_url == 'http://lan-host:8010'
    assert api.build_file_upload_url() == 'http://lan-host:8010/api/files/upload'
    assert api.normalize_server_url('http://old-server:8085/api/artifacts/id/download?x=1') == 'http://lan-host:8010/api/artifacts/id/download?x=1'

    # A spawned Script/Job interpreter resolves the same URL after launch.
    script = 'from client.http.client_api import ClientApiClient; print(ClientApiClient().build_url("/api/jobs/list"))'
    child = subprocess.run([sys.executable, '-c', script, '--profile', 'bind'],
                           cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == 'http://lan-host:8010/api/jobs/list'
    # Child defaults to dev profile unless explicitly given --profile; the
    # inherited endpoint state must still win.
    plain_child = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))
    assert plain_child.returncode == 0, plain_child.stderr
    assert plain_child.stdout.strip() == 'http://lan-host:8010/api/jobs/list'

    # Change is deliberately made through a new session announcement, not a cached ClientApiClient.
    server_endpoint.clear_session_base_url()
    with pytest.raises(RuntimeError, match='until the Bind session'):
        _ = api.base_url
    new_connection = SimpleNamespace(client_session_token='')
    new_dispatcher = ClientInboundMessageDispatcher(new_connection)
    new_dispatcher.dispatch({'type': MSG_TYPE_SESSION_CONFIG, 'server_web_base_url': 'https://gateway.example:443'})
    assert api.base_url == 'https://gateway.example:443'
    new_dispatcher.dispatch({'type': MSG_TYPE_SESSION_CONFIG, 'server_web_base_url': 'http://not-applied.example'})
    assert api.base_url == 'https://gateway.example:443'
    assert api.build_url('/api/jobs/list') == 'https://gateway.example:443/api/jobs/list'
    child = subprocess.run([sys.executable, '-c', script, '--profile', 'bind'],
                           cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == 'https://gateway.example:443/api/jobs/list'


def test_client_api_requests_use_announced_origin_and_session_token(bind_runtime, monkeypatch):
    from client.http.session_auth import clear_token, set_token
    from core.protocol.client_api_auth import CLIENT_SESSION_TOKEN_HEADER
    from client.http import client_api

    calls = []
    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, text='', json=lambda: {'code': 0, 'data': {'ok': True}})

    monkeypatch.setattr(client_api.requests, 'request', fake_request)
    set_token('current-session')
    try:
        server_endpoint.set_session_base_url('http://server-one:8085')
        api = ClientApiClient()
        assert api.post_data('/api/health', json={'check': 1}) == {'ok': True}
        server_endpoint.clear_session_base_url()
        server_endpoint.set_session_base_url('https://server-two.example:443')
        assert api.get_data('/api/jobs/list') == {'ok': True}
        assert calls[0][0:2] == ('POST', 'http://server-one:8085/api/health')
        assert calls[0][2]['headers'][CLIENT_SESSION_TOKEN_HEADER] == 'current-session'
        assert calls[1][0:2] == ('GET', 'https://server-two.example:443/api/jobs/list')
        assert calls[1][2]['headers'][CLIENT_SESSION_TOKEN_HEADER] == 'current-session'
    finally:
        clear_token()


def test_reverse_config_and_explicit_url_still_work(monkeypatch):
    monkeypatch.delenv('RCH_SERVER_WEB_ENDPOINT_STATE', raising=False)
    monkeypatch.setitem(RUNTIME_CONFIG, 'connection_mode', 'reverse')
    expected = f"{RUNTIME_CONFIG['server_web_scheme']}://{RUNTIME_CONFIG['server_web_host']}:{RUNTIME_CONFIG['server_web_port']}"
    api = ClientApiClient()
    assert api.base_url == expected
    assert api.build_url('/api/jobs/list') == expected + '/api/jobs/list'
    custom = ClientApiClient(base_url='https://manual.example', file_transfer_base_url='https://files.example')
    assert custom.build_url('/api/jobs/list') == 'https://manual.example/api/jobs/list'
    assert custom.build_file_upload_url() == 'https://files.example/api/files/upload'


@pytest.mark.parametrize('url', [
    'ftp://server.example', 'http://', 'http://server.example/path',
    'http://user:password@server.example', 'http://server.example?q=1',
    'http://server.example#fragment', 'http://server.example:99999',
    'http://local host:8085', '',
])
def test_invalid_advertised_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_web_origin(url)


def test_server_announces_url_before_online_event():
    messages = []
    events = []
    service = WebConnectionService.__new__(WebConnectionService)
    service.recent_device_store = None
    service.connection_history_store = None
    service.client_session_token_service = SimpleNamespace(issue=lambda session: 'token-from-server')
    service.serialize_connection = lambda session: {'client_id': 'instance-1'}
    service.publish_connection_online = lambda session: events.append('online')
    service.server = SimpleNamespace()

    for protocol, expected in [('bind_tcp', 2), ('tcp', 1)]:
        messages.clear()
        events.clear()
        session = SimpleNamespace(
            listener_protocol=protocol,
            server_web_base_url='http://server-on-lan:8085',
            services=SimpleNamespace(heartbeat_service=SimpleNamespace(mark_connected=lambda: None)),
            send=lambda message: messages.append(message),
        )
        service.handle_connection_registered(session)
        assert len(messages) == expected
        assert messages[0] == {'type': MSG_TYPE_CLIENT_SESSION_TOKEN, 'token': 'token-from-server'}
        if protocol == 'bind_tcp':
            assert messages[1] == {'type': MSG_TYPE_SESSION_CONFIG, 'server_web_base_url': 'http://server-on-lan:8085'}
        assert events == ['online']
