"""Built source bundles, bootstrap selection and Server-side disconnect semantics."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.application.agent.agent_build_bundle import BundleBuilder
from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService
from server.application.web.connection_api import WebConnectionApi
from server.application.connection.connection_service import WebConnectionService

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['reverse', 'bind'])
def test_bundle_default_mode_and_manual_override(tmp_path, mode):
    builder = BundleBuilder(str(ROOT))
    result = builder.build(
        work_dir=str(tmp_path), server_host='192.168.1.10', server_port=9999,
        web_port=8085, build_id='test', build_version='test',
        target_os='mac', target_arch='arm64', connection_mode=mode,
        bind_host='0.0.0.0', bind_port=9443,
    )
    assert result['target_os'] == ''
    assert result['target_arch'] == ''
    with zipfile.ZipFile(result['file_path']) as archive:
        source = archive.read('client/config/config.py').decode()
        assert '_get_connection_mode_override' in source
        assert 'profiles/agent.json' in '\n'.join(archive.namelist())
        settings = json.loads(archive.read('client/config/profiles/agent.json'))
        assert settings['connection_mode'] == mode
        assert settings['bind_port'] == 9443
        if mode == 'bind':
            assert not any(key in settings for key in ('server_web_scheme', 'server_web_host', 'server_web_port', 'server_host', 'server_port'))
        else:
            assert settings['server_web_host'] == '192.168.1.10'
        archive.extractall(tmp_path / 'extracted')
    program = ('import json; from client.config.config import RUNTIME_CONFIG; '
               'print(json.dumps(RUNTIME_CONFIG))')
    def config(*args):
        proc = subprocess.run([sys.executable, '-c', program, *args],
                              cwd=tmp_path / 'extracted', capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)
    assert config()['connection_mode'] == mode
    assert config()['profile_name'] == 'agent'
    other = 'bind' if mode == 'reverse' else 'reverse'
    assert config('--connection-mode', other)['connection_mode'] == other
    assert config(f'--connection-mode={other}')['connection_mode'] == other
    assert config()['client_build_version'] == 'test'
    assert config('--profile', 'bind')['connection_mode'] == 'bind'
    invalid = subprocess.run([sys.executable, '-c', program, '--connection-mode=invalid'],
                             cwd=tmp_path / 'extracted', capture_output=True, text=True)
    assert invalid.returncode != 0
    assert 'connection-mode must be bind or reverse' in invalid.stderr


def test_reverse_mtls_bundle_keeps_identity_separate_from_build(tmp_path):
    builder = BundleBuilder(str(ROOT))
    result = builder.build(
        work_dir=str(tmp_path), server_host='192.168.1.10', server_port=9443,
        web_port=8085, build_id='test-mtls', build_version='test-mtls',
        target_os='mac', target_arch='arm64', connection_mode='reverse',
        listener_protocol='mtls_tcp',
    )
    with zipfile.ZipFile(result['file_path']) as archive:
        settings = json.loads(archive.read('client/config/profiles/agent.json'))
    assert settings['connection_mode'] == 'reverse'
    assert settings['server_transport'] == 'mtls_tcp'
    assert 'server_tls_fingerprint' not in settings
    assert 'client.key' not in archive.namelist()


def test_bootstrap_passes_mode_to_build_request_and_starts_without_flags():
    service = AgentBootstrapScriptService()
    data = dict(server_host='192.168.1.10', server_port=9999, web_port=8085,
                connection_mode='bind', bind_host='0.0.0.0', bind_port=9443)
    python = service.generate_python_script(data)
    powershell = service.generate_powershell_script(data)
    assert 'CONNECTION_MODE = "bind"' in python
    assert 'SERVER_TRANSPORT = "tcp"' in python
    assert "'connection_mode': CONNECTION_MODE" in python
    assert 'subprocess.Popen([str(python), str(script)], **kwargs)' in python
    assert '$connectionMode="bind"' in powershell
    assert 'connection_mode=$connectionMode' in powershell
    assert '$serverTransport="tcp"' in powershell
    assert 'ArgumentList @($script)' in powershell or '$script' in powershell
    with pytest.raises(ValueError, match='connection_mode'):
        service.normalize_bootstrap_payload({**data, 'connection_mode': 'invalid'})


class _Session:
    def __init__(self, protocol):
        self.listener_protocol = protocol
        self.requested = 0

    def request_disconnect(self):
        self.requested += 1


def test_server_selects_current_session_for_disconnect():
    sessions = {'bind-id': _Session('bind_tcp'), 'reverse-id': _Session('tcp')}
    class Server:
        def get_target_connection_by_client_id(self, client_id):
            return sessions[client_id]
    class Connector:
        def __init__(self):
            self.closed = []
        def disconnect(self, client_id):
            self.closed.append(client_id)
    service = WebConnectionService.__new__(WebConnectionService)
    service.server = Server()
    connector = Connector()
    api = WebConnectionApi(service, bind_connector=connector)
    assert api.disconnect_connection('bind-id') == {'client_id': 'bind-id', 'mode': 'bind'}
    assert api.disconnect_connection('reverse-id') == {'client_id': 'reverse-id', 'mode': 'reverse'}
    assert connector.closed == ['bind-id']
    assert sessions['bind-id'].requested == 0
    assert sessions['reverse-id'].requested == 1


def test_bind_bootstrap_requires_only_web_address_and_client_listen_settings():
    service = AgentBootstrapScriptService()
    payload = dict(web_host='192.168.1.50', web_port=8085, connection_mode='bind',
                   bind_host='0.0.0.0', bind_port=9443)
    normalized = service.normalize_bootstrap_payload(payload)
    assert normalized['web_host'] == '192.168.1.50'
    assert 'server_transport' not in normalized  # Default TCP is implicit.
    python_script = service.generate_python_script(payload)
    powershell = service.generate_powershell_script(payload)
    compile(python_script, 'bootstrap_bind.py', 'exec')
    assert 'CONNECTION_MODE = "bind"' in python_script
    assert "if CONNECTION_MODE == 'bind':" in python_script
    assert "payload.update(bind_host=BIND_HOST, bind_port=BIND_PORT)" in python_script
    assert "server_host=SERVER_HOST, server_port=SERVER_PORT" in python_script
    assert "if ($connectionMode -eq 'bind')" in powershell
    assert "$body['bind_host'] = $bindHost" in powershell
    assert "$body['server_transport'] = $serverTransport" in powershell
    assert "$body['server_host'] = $ip" in powershell
    with pytest.raises(ValueError, match='web_host is required'):
        service.normalize_bootstrap_payload({**payload, 'web_host': ''})
    with pytest.raises(ValueError, match='server_host is required'):
        service.normalize_bootstrap_payload(dict(connection_mode='reverse', server_port=9999, web_port=8085))


def test_generated_python_bootstrap_sends_mode_specific_build_payloads():
    service = AgentBootstrapScriptService()
    for mode in ('bind', 'reverse'):
        request = dict(connection_mode=mode, web_port=8085,
                       bind_host='0.0.0.0', bind_port=9443)
        if mode == 'bind':
            request['web_host'] = '192.168.1.50'
            request['server_transport'] = 'mtls_tcp'
        else:
            request.update(server_host='192.168.1.50', server_port=9999, listener_id='listener-mtls')
        source = service.generate_python_script(request)
        scope = {'__name__': 'generated_bootstrap_test'}
        exec(compile(source, 'generated_bootstrap.py', 'exec'), scope)
        sent = []
        def fake_request(url, payload):
            sent.append((url, payload))
            return json.dumps({'code': 0, 'data': {'file_name': 'test.zip', 'build_version': 'test'}}).encode()
        scope['request_bytes'] = fake_request
        scope['log'] = lambda message: None
        scope['build_bundle']()
        assert sent[0][0] == 'http://192.168.1.50:8085/api/agent/build'
        build = sent[0][1]
        assert build['connection_mode'] == mode
        if mode == 'bind':
            assert not any(key in build for key in ('server_web_host', 'server_web_scheme', 'web_port'))
            assert build['bind_host'] == '0.0.0.0'
            assert build['bind_port'] == 9443
            assert build['server_transport'] == 'mtls_tcp'
            assert 'listener_id' not in build
            assert 'server_host' not in build and 'server_port' not in build
        else:
            assert build['server_web_host'] == '192.168.1.50'
            assert build['server_host'] == '192.168.1.50'
            assert build['server_port'] == 9999
            assert build['listener_id'] == 'listener-mtls'
            assert 'server_transport' not in build
            assert 'bind_host' not in build and 'bind_port' not in build


@pytest.mark.parametrize('transport', ['tcp', 'mtls_tcp'])
def test_bind_bootstrap_protocol_is_forwarded_in_both_generated_scripts(transport):
    service = AgentBootstrapScriptService()
    request = dict(web_host='192.168.1.50', web_port=8085, connection_mode='bind',
                   bind_host='0.0.0.0', bind_port=9443, server_transport=transport)
    normalized = service.normalize_bootstrap_payload(request)
    assert ('server_transport' in normalized) == (transport == 'mtls_tcp')
    python_script = service.generate_python_script(request)
    powershell_script = service.generate_powershell_script(request)
    assert f'SERVER_TRANSPORT = "{transport}"' in python_script
    assert f'$serverTransport="{transport}"' in powershell_script
    assert "if ($serverTransport -ne 'tcp') { $body['server_transport'] = $serverTransport }" in powershell_script
    assert "$body['listener_id'] = $listenerId" in powershell_script  # Reverse only.
    scope = {'__name__': 'generated_bootstrap_test'}
    exec(compile(python_script, 'generated_bootstrap.py', 'exec'), scope)
    captured = []
    scope['request_bytes'] = lambda url, body: (captured.append((url, body)) or
        json.dumps({'code': 0, 'data': {'file_name': 'test.zip', 'build_version': 'test'}}).encode())
    scope['log'] = lambda message: None
    scope['build_bundle']()
    assert captured[0][1].get('server_transport', 'tcp') == transport
    assert ('server_transport' in captured[0][1]) == (transport == 'mtls_tcp')
    assert 'listener_id' not in captured[0][1]


def test_reverse_bootstrap_only_sends_listener_identity_for_protocol_selection():
    service = AgentBootstrapScriptService()
    request = dict(connection_mode='reverse', server_host='192.168.1.50',
                   server_port=19998, web_port=8085, listener_id='mtls-listener')
    assert 'server_transport' not in service.normalize_bootstrap_payload(request)
    source = service.generate_python_script(request)
    scope = {'__name__': 'generated_bootstrap_test'}
    exec(compile(source, 'generated_bootstrap.py', 'exec'), scope)
    captured = []
    scope['request_bytes'] = lambda url, body: (captured.append(body) or
        json.dumps({'code': 0, 'data': {'file_name': 'test.zip', 'build_version': 'test'}}).encode())
    scope['log'] = lambda message: None
    scope['build_bundle']()
    assert captured[0]['listener_id'] == 'mtls-listener'
    assert 'server_transport' not in captured[0]
    powershell = service.generate_powershell_script(request)
    assert 'if ($listenerId) { $body[\'listener_id\'] = $listenerId }' in powershell
    assert "if ($serverTransport -ne 'tcp') { $body['server_transport'] = $serverTransport }" in powershell
