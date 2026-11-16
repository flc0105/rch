"""Keep Update listener selection and recovery pacing within their existing layers."""
import runpy
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from client.app.client import Client


def _manager(tmp_path, monkeypatch):
    config = types.ModuleType('server.config.config')
    config.SERVER_RUNTIME_DIR = str(tmp_path)
    config.WEB_PORT = 8085
    config.WEB_WS_PORT = 8086
    monkeypatch.setitem(sys.modules, 'server.config.config', config)
    from server.runtime.listener_manager import ListenerManager
    manager = ListenerManager(SimpleNamespace(address=('127.0.0.1', 9999)),
                              str(tmp_path / 'listeners.json'))
    manager._configs = [
        {'id': 'tcp-default', 'name': 'TCP', 'protocol': 'tcp', 'port': 9999, 'enabled': True},
        {'id': 'tls-local', 'name': 'TLS', 'protocol': 'tls_tcp', 'port': 9443, 'enabled': True},
    ]
    monkeypatch.setattr(manager, 'certificate_fingerprint',
                        lambda listener_id: 'a' * 64 if listener_id == 'tls-local' else '')
    monkeypatch.setattr(manager, 'build_settings',
                        lambda listener_id, port, builder: {
                            'listener_protocol': manager.get(listener_id)['protocol'],
                            'tls_fingerprint': 'a' * 64 if listener_id == 'tls-local' else '',
                        })
    return manager


def _build_endpoint(monkeypatch, manager, tmp_path, payload):
    """Exercise the real build route with HTTP adapters replaced (Flask unavailable here)."""
    fake_flask = types.ModuleType('flask')

    class Blueprint:
        def __init__(self, *args):
            self.handlers = {}

        def _route(self, method, path):
            def register(func):
                self.handlers[method, path] = func
                return func
            return register

        def post(self, path): return self._route('POST', path)
        def get(self, path): return self._route('GET', path)
        def delete(self, path): return self._route('DELETE', path)

    fake_flask.Blueprint = Blueprint
    fake_flask.send_file = lambda *args, **kw: None
    monkeypatch.setitem(sys.modules, 'flask', fake_flask)

    responder_mod = types.ModuleType('server.web.api_response')
    responder_mod.WebApiResponder = lambda: SimpleNamespace(json_endpoint=lambda func, **kwargs: func())
    monkeypatch.setitem(sys.modules, 'server.web.api_response', responder_mod)

    auth_mod = types.ModuleType('server.web.auth_guard')
    auth_mod.allow_anonymous = lambda func: func
    monkeypatch.setitem(sys.modules, 'server.web.auth_guard', auth_mod)

    parser_mod = types.ModuleType('server.web.request_parsers')
    parser_mod.get_json_payload = lambda: dict(payload)
    monkeypatch.setitem(sys.modules, 'server.web.request_parsers', parser_mod)

    artifact = tmp_path / 'bundle.zip'
    artifact.write_bytes(b'bundle')
    build_agent = Mock(return_value={'file_name': 'bundle.zip'})
    agent_api = SimpleNamespace(build_agent=build_agent,
                                get_built_agent_file_path=lambda filename: str(artifact))
    server = SimpleNamespace(listener_manager=manager,
                             web_service=SimpleNamespace(agent_api=agent_api))
    route_path = Path(__file__).parents[2] / 'server' / 'web' / 'routes' / 'agent.py'
    blueprint = runpy.run_path(str(route_path))['create_agent_blueprint'](server)
    return blueprint.handlers['POST', '/api/agent/build'], build_agent


def _payload(**overrides):
    values = {'source': 'update', 'server_host': '127.0.0.1', 'server_port': 9443,
              'web_port': 8085, 'builder': 'python', 'target_os': '',
              'server_transport': 'tls_tcp', 'server_tls_fingerprint': 'a' * 64,
              'listener_id': 'tls-local'}
    values.update(overrides)
    return values


def test_update_build_rejects_tcp_claim_for_explicit_tls_listener(tmp_path, monkeypatch):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, _payload(server_transport='tcp', server_tls_fingerprint=''))
    with pytest.raises(ValueError, match='Update listener does not match connection settings'):
        endpoint()
    builder.assert_not_called()


def test_update_build_rejects_id_inconsistent_with_valid_transport(tmp_path, monkeypatch):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, _payload(listener_id='tcp-default'))
    with pytest.raises(ValueError, match='Update listener does not match connection settings'):
        endpoint()
    builder.assert_not_called()


def test_update_build_valid_tls_keeps_server_pinned_settings(tmp_path, monkeypatch):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, _payload())
    assert endpoint()['file_name'] == 'bundle.zip'
    kwargs = builder.call_args.kwargs
    assert kwargs['listener_protocol'] == 'tls_tcp'
    assert kwargs['tls_fingerprint'] == 'a' * 64
    assert kwargs['listener_id'] == 'tls-local'


def test_update_build_plain_tcp_is_unchanged(tmp_path, monkeypatch):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, _payload(server_port=9999, listener_id='tcp-default',
                                                           server_transport='tcp', server_tls_fingerprint=''))
    endpoint()
    assert builder.call_args.kwargs['listener_protocol'] == 'tcp'
    assert builder.call_args.kwargs['tls_fingerprint'] == ''


def test_manual_bundle_build_without_listener_preserves_default_tcp(tmp_path, monkeypatch):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, _payload(source='manual', server_port=9999,
                                                           listener_id='', server_transport=''))
    endpoint()
    assert builder.call_args.kwargs['listener_protocol'] == 'tcp'
    assert builder.call_args.kwargs['listener_id'] == ''


def test_update_build_rejects_wrong_tls_certificate_pin(tmp_path, monkeypatch):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, _payload(server_tls_fingerprint='b' * 64))
    with pytest.raises(ValueError, match='Update certificate fingerprint does not match a configured listener'):
        endpoint()
    builder.assert_not_called()


@pytest.mark.parametrize('listener_id', ['', 'tcp-default'])
def test_update_tcp_preserves_forwarded_endpoints(tmp_path, monkeypatch, listener_id):
    manager = _manager(tmp_path, monkeypatch)
    # The actual update payload does not include a listener ID.
    endpoint, builder = _build_endpoint(monkeypatch, manager, tmp_path,
        _payload(server_host='127.0.0.1', server_port=19999, web_port=18085,
                 server_web_host='127.0.0.1', listener_id=listener_id,
                 server_transport='tcp', server_tls_fingerprint=''))
    endpoint()
    assert builder.call_args.args[:3] == ('127.0.0.1', 19999, 18085)
    assert builder.call_args.args[7] == '127.0.0.1'
    assert builder.call_args.kwargs['listener_protocol'] == 'tcp'
    assert builder.call_args.kwargs['tls_fingerprint'] == ''


def test_update_tcp_does_not_require_unique_or_enabled_listener(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    manager._configs.append({'id': 'tcp-other', 'name': 'Other', 'protocol': 'tcp',
                             'port': 19999, 'enabled': True})
    endpoint, builder = _build_endpoint(monkeypatch, manager, tmp_path,
        _payload(server_port=19999, listener_id='', server_transport='tcp', server_tls_fingerprint=''))
    endpoint()
    assert builder.call_args.kwargs['listener_id'] == ''
    for item in manager._configs:
        item['enabled'] = False
    endpoint()
    assert builder.call_args.kwargs['listener_id'] == ''
    assert builder.call_args.kwargs['listener_protocol'] == 'tcp'


@pytest.mark.parametrize('listener_id', ['', 'tls-local'])
def test_update_tls_forwarded_port_keeps_server_pin(tmp_path, monkeypatch, listener_id):
    manager = _manager(tmp_path, monkeypatch)
    endpoint, builder = _build_endpoint(monkeypatch, manager, tmp_path,
        _payload(server_port=19443, listener_id=listener_id))
    endpoint()
    assert builder.call_args.args[1] == 19443
    assert builder.call_args.kwargs['tls_fingerprint'] == 'a' * 64
    assert builder.call_args.kwargs['listener_id'] == 'tls-local'


@pytest.mark.parametrize('port', [-1, 65536])
def test_update_rejects_invalid_dial_port(tmp_path, monkeypatch, port):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
        tmp_path, _payload(server_port=port, listener_id='', server_transport='tcp', server_tls_fingerprint=''))
    with pytest.raises(ValueError, match='server_port must be between 1 and 65535'):
        endpoint()
    builder.assert_not_called()


def test_update_tls_requires_pin(tmp_path, monkeypatch):
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, _payload(server_tls_fingerprint=''))
    with pytest.raises(ValueError, match='pinned server certificate'):
        endpoint()
    builder.assert_not_called()


def test_update_build_real_bundle_keeps_forwarded_config(tmp_path, monkeypatch):
    import shutil
    import zipfile
    from server.application.agent.agent_build_bundle import BundleBuilder

    payload = _payload(server_host='127.0.0.1', server_port=19999, web_port=18085,
                       server_web_host='frp.example.test', listener_id='',
                       server_transport='tcp', server_tls_fingerprint='')
    endpoint, builder = _build_endpoint(monkeypatch, _manager(tmp_path, monkeypatch),
                                        tmp_path, payload)

    def build_real(*args, **kwargs):
        work = tmp_path / 'build'
        work.mkdir()
        result = BundleBuilder(str(Path(__file__).parents[2])).build(
            work_dir=str(work), server_host=args[0], server_port=args[1], web_port=args[2],
            target_os=args[3], target_arch=args[5], server_web_scheme=args[6],
            server_web_host=args[7], listener_protocol=kwargs['listener_protocol'],
            tls_fingerprint=kwargs['tls_fingerprint'], build_id='test', build_version='test')
        shutil.copyfile(result['file_path'], tmp_path / 'bundle.zip')
        return {'file_name': 'bundle.zip'}

    builder.side_effect = build_real
    endpoint()
    with zipfile.ZipFile(tmp_path / 'bundle.zip') as archive:
        assert archive.testzip() is None
        config = {}
        exec(compile(archive.read('client/config/config.py'), 'config.py', 'exec'), config)
        assert config['SERVER_ADDR'] == ('127.0.0.1', 19999)
        assert config['SERVER_WEB_HOST'] == 'frp.example.test'
        assert config['SERVER_WEB_PORT'] == 18085
        assert config['SERVER_TRANSPORT'] == 'tcp'
        assert 'client/scripts/manager.py' in archive.namelist()
        assert 'client/remote_files/manager.py' in archive.namelist()
        assert 'client/jobs/control.py' in archive.namelist()
        assert 'client/commands/runtime/control_dispatcher.py' not in archive.namelist()


def test_abnormal_disconnect_waits_before_first_reconnect():
    client = Client.__new__(Client)
    client.RECONNECT_INTERVAL = 5
    client.connection_lifecycle = SimpleNamespace(is_paused=False, reset_connection=Mock())
    client.connect = Mock()
    with patch('client.bootstrap.client_app.time.sleep') as sleep:
        client._recover_from_connection_error(OSError('broken transport'))
    sleep.assert_called_once_with(5)
    client.connection_lifecycle.reset_connection.assert_called_once()
    client.connect.assert_called_once()


def test_repeated_short_lived_successes_are_throttled():
    client = Client.__new__(Client)
    client.RECONNECT_INTERVAL = 5
    client.connection_lifecycle = SimpleNamespace(is_paused=False, reset_connection=Mock())
    client.connect = Mock()
    with patch('client.bootstrap.client_app.time.sleep') as sleep:
        client._recover_from_connection_error(OSError('first loss'))
        client._recover_from_connection_error(OSError('second loss'))
    assert sleep.call_count == 2
    sleep.assert_any_call(5)
    assert client.connect.call_count == 2


def test_pause_during_backoff_does_not_restart_connection():
    client = Client.__new__(Client)
    client.RECONNECT_INTERVAL = 5
    state = SimpleNamespace(is_paused=False, reset_connection=Mock())
    client.connection_lifecycle = state
    client.connect = Mock()
    with patch('client.bootstrap.client_app.time.sleep', side_effect=lambda delay: setattr(state, 'is_paused', True)):
        client._recover_from_connection_error(OSError('transport lost'))
    client.connection_lifecycle.reset_connection.assert_not_called()
    client.connect.assert_not_called()
