"""Unified Client Session Token access, authorization, and lifecycle."""
from types import SimpleNamespace

import pytest

from client.commands.common.services.interaction_service import CommandInteractionError, CommandInteractions
from client.connection.message_dispatcher import ClientInboundMessageDispatcher
from client.http.session_auth import clear_token, get_token
from core.protocol.client_api_auth import CLIENT_SESSION_TOKEN_HEADER
from core.protocol.message_types import MSG_TYPE_CLIENT_SESSION_TOKEN
from server.application.auth.client_api_policy import ClientApiPolicy
from server.application.auth.client_session_token_service import ClientSessionTokenService
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


def session(client_id='client-1', machine_id='machine-1'):
    return SimpleNamespace(session_info=SimpleNamespace(client_id=client_id, machine_id=machine_id))


def test_single_session_token_covers_registered_client_apis_not_admin_commands():
    service = ClientSessionTokenService()
    connected = session()
    token = service.issue(connected)
    headers = {CLIENT_SESSION_TOKEN_HEADER: token}
    allowed = [
        ('GET', '/api/scripts/download'),
        ('GET', '/api/jobs/list'),
        ('GET', '/api/jobs/download'),
        ('POST', '/api/background-jobs/report'),
        ('POST', '/api/device-events'),
        ('POST', '/api/agent/build'),
        ('GET', '/api/agent/download/example.zip'),
        ('GET', '/api/artifacts'),
        ('GET', '/api/artifacts/f1/download'),
        ('GET', '/api/external-tools/catalog'),
        ('POST', '/api/interactions/client/request'),
        ('GET', '/api/keychains'),
        ('GET', '/api/keychains/secret-1'),
        ('POST', '/api/keychains'),
        ('POST', '/api/keychains/resolve'),
        ('PUT', '/api/keychains/secret-1'),
        ('DELETE', '/api/keychains/secret-1'),
        ('GET', '/api/connections/client-1/pinned_paths'),
    ]
    for method, path in allowed:
        assert service.authenticate(method=method, path=path, headers=headers)['session'] is connected
    forbidden = [
        ('POST', '/api/connections/client-1/command'),
        ('POST', '/api/connections/other/command'),
        ('GET', '/api/connections/other/pinned_paths'),
        ('GET', '/api/agents'),
        ('GET', '/api/auth/info'),
        ('POST', '/api/auth/token/reset'),
        ('POST', '/api/scripts/save'),
        ('POST', '/api/interactions/x/answer'),
        ('GET', '/api/interactions/client/request'),
    ]
    for method, path in forbidden:
        assert service.authenticate(method=method, path=path, headers=headers) is None, (method, path)
    assert service.authenticate(method='GET', path='/api/keychains',
                                headers={CLIENT_SESSION_TOKEN_HEADER: 'invalid'}) is None
    assert service.authenticate(method='GET', path='/api/keychains',
                                headers={'X-Script-Grant-Token': token}) is None
    service.revoke(connected)
    assert service.identify(token) is None


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


def test_credential_received_and_cleared_on_disconnect():
    from client.connection.server_connection import ServerConnection

    clear_token()
    sock = ServerConnection()
    try:
        ClientInboundMessageDispatcher(sock).dispatch({'type': MSG_TYPE_CLIENT_SESSION_TOKEN, 'token': 'a-token'})
        assert sock.client_session_token == 'a-token'
        assert get_token() == 'a-token'
        sock.mark_disconnected()
        assert sock.client_session_token == ''
        assert get_token() == ''
    finally:
        clear_token()


def test_command_acmd_script_dispatch_never_issues_execution_token():
    channel = ClientSessionCommandChannel(SimpleNamespace())
    assert 'extra' not in channel.build_command_payload('getinfo')
    assert channel.build_command_payload('acmd launchd status', 'acmd', {'x': 1})['extra'] == {'x': 1}
    assert channel.build_command_payload('print(1)', 'script', {'a': 1})['extra'] == {'a': 1}


def test_command_interaction_uses_shared_header_and_current_command(monkeypatch):
    calls = []
    monkeypatch.setattr('client.http.client_api.ClientApiClient.post_data',
                        lambda self, path, **kw: calls.append((path, kw)) or {'status': 'answered', 'value': True})
    owner = SimpleNamespace(socket=SimpleNamespace(client_session_token='session-token'), command_id=44,
                            _checkpoint=lambda **_kw: None)
    assert CommandInteractions(owner).confirm('Proceed?') is True
    assert calls[0][1]['headers'] == {CLIENT_SESSION_TOKEN_HEADER: 'session-token'}
    assert calls[0][1]['json']['command_id'] == 44
    owner.command_id = None
    with pytest.raises(CommandInteractionError, match='active Client command connection'):
        CommandInteractions(owner).confirm('Proceed?')


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


def test_script_metadata_no_longer_keeps_api_grants():
    from core.utils.script_metadata import normalize_script_metadata
    value = normalize_script_metadata({'name': 'task', 'api_grants': ['interactions:request']})
    assert 'api_grants' not in value


def test_registration_sends_one_token_before_online():
    from server.application.connection.connection_service import WebConnectionService
    events = []
    service = ClientSessionTokenService()
    subject = WebConnectionService(server=None, event_bus=None, artifact_service=None,
                                   client_session_token_service=service)
    subject.serialize_connection = lambda _session: {'client_id': 'reg'}
    subject.publish_connection_online = lambda _session: events.append('online')
    conn = session('reg')
    conn.services = SimpleNamespace(heartbeat_service=SimpleNamespace(mark_connected=lambda: events.append('heartbeat')))
    conn.send = lambda msg: events.append(msg)
    subject.handle_connection_registered(conn)
    assert events[0] == 'heartbeat'
    assert events[1]['type'] == MSG_TYPE_CLIENT_SESSION_TOKEN
    assert service.identify(events[1]['token'])['session'] is conn
    assert events[2] == 'online'


def test_client_api_policy_is_explicit_and_exact():
    policy = ClientApiPolicy()
    assert policy.allows('GET', '/api/artifacts/a/raw')
    assert not policy.allows('GET', '/api/artifacts/a/raw/other')
    assert not policy.allows('POST', '/api/artifacts/a/raw')
    assert not policy.allows('POST', '/api/connections/x/command')


def test_web_auth_guard_preserves_admin_and_restricts_client_token(monkeypatch):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    request = SimpleNamespace(method='GET', path='/api/keychains', headers={})
    flask = types.ModuleType('flask')
    flask.request = request
    flask.current_app = SimpleNamespace()
    flask.session = {}
    flask.g = SimpleNamespace()
    config = types.ModuleType('server.config.config')
    config.ADMIN_API_TOKEN = 'admin-secret'
    config.WEB_SESSION_SECRET = 'secret-key'
    config.ADMIN_USERNAME = 'admin'
    config.ADMIN_PASSWORD_HASH = 'hash'
    path = Path(__file__).resolve().parents[2] / 'server/web/auth_guard.py'
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, 'flask', flask)
        mp.setitem(sys.modules, 'server.config.config', config)
        spec = importlib.util.spec_from_file_location('test_only_auth_guard_unified', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    svc = ClientSessionTokenService()
    token = svc.issue(session())
    guard = module.WebAuthGuard(client_session_token_service=svc)
    request.headers = {CLIENT_SESSION_TOKEN_HEADER: token}
    assert guard.is_authenticated() is True
    assert flask.g.client_session_identity['machine_id'] == 'machine-1'
    request.path = '/api/connections/client-1/command'
    request.method = 'POST'
    assert guard.is_authenticated() is False
    request.headers = {'Authorization': 'Bearer admin-secret'}
    assert guard.is_authenticated() is True
    request.headers = {CLIENT_SESSION_TOKEN_HEADER: 'invalid'}
    assert guard.is_authenticated() is False


def test_keychains_only_own_machine_and_shared_for_client(monkeypatch):
    import sys
    import types
    import importlib.util
    from pathlib import Path

    # Isolate Keychain API from an optional Werkzeug/AdminAuth dependency.
    stub = types.ModuleType('server.application.keychains.keychain_store')
    stub.KeychainStore = type('KeychainStore', (), {
        'SHARED_MACHINE_ID': '__shared__', 'SHARED_HOSTNAME': 'Shared',
    })
    path = Path(__file__).resolve().parents[2] / 'server/application/web/keychain_api.py'
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, stub.__name__, stub)
        spec = importlib.util.spec_from_file_location('test_unified_keychain_api', path)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
    WebKeychainApi = loaded.WebKeychainApi

    class Store:
        def __init__(self):
            self.items = {
                'mine': {'machine_id': 'machine-1', 'name': 'mine'},
                'shared': {'machine_id': '__shared__', 'name': 'shared'},
                'other': {'machine_id': 'machine-2', 'name': 'other'},
            }
        def list_stored_machines(self):
            return [{'machine_id': 'machine-1', 'hostname': 'Me'},
                    {'machine_id': 'machine-2', 'hostname': 'Other'}]
        def list_items(self, machine, reveal=False):
            return [v for v in self.items.values() if v['machine_id'] == machine]
        def get_item(self, item_id, reveal=False):
            return self.items.get(item_id)
        def get_item_by_name(self, machine, name, kind='', reveal=False):
            return {'machine_id': machine, 'name': name}
        def create_item(self, item):
            return dict(item)
        def public_item(self, item):
            return item
        def update_item(self, item_id, item):
            return dict(item)
        def delete_item(self, item_id):
            return self.items[item_id]

    store = Store()
    fake_flask = types.ModuleType('flask')
    fake_flask.g = SimpleNamespace(client_session_identity={'client_id': 'client-1', 'machine_id': 'machine-1'})
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, 'flask', fake_flask)
        api = WebKeychainApi(None, store, SimpleNamespace(get_connections_payload=lambda: []))
        assert [v['name'] for v in api.list_keychains()['items']] == ['mine']
        assert [v['name'] for v in api.list_keychains('__shared__')['items']] == ['shared']
        assert {v['machine_id'] for v in api.list_keychains()['machines']} == {'machine-1', '__shared__'}
        assert api.get_keychain_item('mine')['item']['name'] == 'mine'
        assert api.get_keychain_item('shared')['item']['name'] == 'shared'
        assert api.resolve_keychain_item({'name': 'shared', 'scope': 'shared'})['item']['name'] == 'shared'
        for name in ['other']:
            with pytest.raises(PermissionError):
                api.get_keychain_item(name)
            with pytest.raises(PermissionError):
                api.delete_keychain_item(name)
            with pytest.raises(PermissionError):
                api.update_keychain_item(name, {'name': 'edit'})
        with pytest.raises(PermissionError):
            api.list_keychains('machine-2')
        with pytest.raises(PermissionError):
            api.resolve_keychain_item({'name': 'other', 'machine_id': 'machine-2'})
        with pytest.raises(PermissionError):
            api.create_keychain_item({'name': 'other', 'machine_id': 'machine-2'})
        assert api.update_keychain_item('mine', {'name': 'new'})['item']['machine_id'] == 'machine-1'
        with pytest.raises(PermissionError):
            api.update_keychain_item('mine', {'name': 'move', 'machine_id': 'machine-2'})


def test_interaction_request_validates_current_task_using_client_identity(monkeypatch):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    class Blueprint:
        def __init__(self, *_a, **_k):
            self.routes = {}
        def get(self, path):
            return lambda fn: self._put(('GET', path), fn)
        def post(self, path):
            return lambda fn: self._put(('POST', path), fn)
        def _put(self, key, fn):
            self.routes[key] = fn
            return fn

    class Responder:
        def json_endpoint(self, func):
            return func()

    flask = types.ModuleType('flask')
    flask.Blueprint = Blueprint
    flask.request = SimpleNamespace(payload={'command_id': 3, 'kind': 'confirm'},
                                    get_json=lambda **_kw: flask.request.payload)
    current = session()
    current.get_foreground_task = lambda: {'command_id': 3, 'task_id': 'task-1'}
    flask.g = SimpleNamespace(client_session_identity={'client_id': 'client-1', 'session': current})
    response = types.ModuleType('server.web.api_response')
    response.WebApiResponder = Responder
    path = Path(__file__).resolve().parents[2] / 'server/web/routes/interactions.py'
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, 'flask', flask)
        mp.setitem(sys.modules, 'server.web.api_response', response)
        spec = importlib.util.spec_from_file_location('test_unified_interaction_route', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    received = []
    fake = SimpleNamespace(
        web_service=SimpleNamespace(task_store=SimpleNamespace(get_task=lambda _id: {
            'client_id': 'client-1', 'tab_id': 'tab-1',
        }), interaction_broker=SimpleNamespace(request=lambda **kw: received.append(kw) or {'ok': True})),
        get_target_connection_by_client_id=lambda cid: current,
    )
    action = module.create_interaction_blueprint(fake).routes[('POST', '/api/interactions/client/request')]
    assert action()['ok'] is True
    assert received[-1]['client_id'] == 'client-1'
    flask.request.payload['command_id'] = 99
    with pytest.raises(ValueError, match='active foreground command'):
        action()
    flask.request.payload['command_id'] = 3
    fake.get_target_connection_by_client_id = lambda cid: session()
    with pytest.raises(ValueError, match='no longer active'):
        action()
