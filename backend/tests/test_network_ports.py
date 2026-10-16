"""Socket/Web are the only configurable server ports; file HTTP is Web+1."""
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from server.application.agent.agent_bootstrap_script_service import AgentBootstrapScriptService
from server.application.agent.agent_builder import AgentBuilder
from server.application.agent.agent_build_utils import inject_python_client_config

BACKEND = Path(__file__).resolve().parents[1]


def _read_server_ports(*, socket='9999', web='8085'):
    # Stub only the authenticator so a port-config test does not create credentials.
    script = '''
import sys, types, json
stub=types.ModuleType("server.config.admin_auth")
stub.load_admin_auth=lambda path: {"username":"admin","password":"test","api_token":"test","session_secret":"test"}
sys.modules["server.config.admin_auth"] = stub
from server.config import config
print(json.dumps({"socket":config.SOCKET_PORT, "web":config.WEB_PORT,
 "file":config.WEB_FILE_TRANSFER_PORT,"base":config.WEB_PUBLIC_BASE_URL}))
'''
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, PYTHONPATH=str(BACKEND), RCH_SOCKET_PORT=socket, RCH_WEB_PORT=web)
        return subprocess.run([sys.executable, '-c', script], cwd=tmp, env=env, capture_output=True, text=True)


def test_default_ports_and_override():
    for sock, web in [('9999', '8085'), ('12000', '9000')]:
        result = _read_server_ports(socket=sock, web=web)
        assert result.returncode == 0, result.stderr
        values = json.loads(result.stdout)
        assert values == {'socket': int(sock), 'web': int(web), 'file': int(web) + 1,
                          'base': f'http://127.0.0.1:{web}'}


@pytest.mark.parametrize('socket,web', [('9000','9000'), ('9001','9000'), ('9999','65535'), ('0','8085'), ('9999','0')])
def test_invalid_port_combinations_fail_startup(socket, web):
    result = _read_server_ports(socket=socket, web=web)
    assert result.returncode != 0
    assert 'Invalid or overlapping RCH socket/web/file ports' in result.stderr


def test_bootstrap_requests_two_ports_only():
    service = AgentBootstrapScriptService()
    payload = {'server_host': '10.2.3.4', 'server_port': 12000, 'web_port': 9000}
    params = service.normalize_bootstrap_payload(payload)
    assert params['web_port'] == 9000
    assert 'file_transfer_port' not in params
    python_script = service.generate_python_script(payload)
    ast.parse(python_script)
    assert '"file_transfer_port"' not in python_script
    assert 'WEB_PORT = 9000' in python_script
    ps_script = service.generate_powershell_script(payload)
    assert 'file_transfer_port' not in ps_script and '$webPort=9000' in ps_script
    with pytest.raises(ValueError, match='web_port'):
        service.normalize_bootstrap_payload({**payload, 'web_port': 65535})


def test_builder_derives_file_port_before_build():
    builder = AgentBuilder.__new__(AgentBuilder)
    with tempfile.TemporaryDirectory() as output:
        builder.output_dir = output
        builder.source_dir = output
        seen = {}
        def build_bundle(**kwargs):
            seen.update(kwargs)
            path = os.path.join(kwargs['work_dir'], 'test.zip')
            Path(path).write_bytes(b'ok')
            return {'file_path': path, 'file_name': 'test.zip', 'target_os': 'bundle', 'warnings': []}
        with patch('server.application.agent.agent_build_bundle.BundleBuilder.build', side_effect=build_bundle):
            builder.build_agent('example.test', 9999, 9000, builder='bundle')
        assert seen['web_port'] == 9000
        assert seen['file_transfer_port'] == 9001


def test_bundled_client_config_derives_file_port():
    # The local Client profile and source-bundle generated template should not have a third config knob.
    import json as json_module
    for profile in ('dev', 'prod'):
        data = json_module.loads((BACKEND / 'client' / 'config' / 'profiles' / f'{profile}.json').read_text())
        assert 'server_file_transfer_port' not in data
    text = (BACKEND / 'client' / 'config' / 'config.py').read_text()
    assert "SERVER_FILE_TRANSFER_PORT = int(SERVER_WEB_PORT) + 1" in text


def test_generated_agent_config_contains_no_independent_file_port():
    builder = AgentBuilder.__new__(AgentBuilder)
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        builder.source_dir = temporary
        for subdir in ('client/config', 'client-go/config', 'go-loader/config'):
            (work / subdir).mkdir(parents=True)
        with patch('server.application.agent.agent_build_utils.build_client_revision_manifest',
                   return_value={'revision':'test-revision','parts':{},'files':{}}):
            inject_python_client_config(temporary, temporary, 'some.host', 12000, 9000, 9001, 'test')
        from importlib import import_module
        from importlib.util import find_spec
        go_name = 'server.application.agent.agent_build_client_go'
        loader_name = 'server.application.agent.agent_build_go_loader'
        if find_spec(go_name):
            import_module(go_name).ClientGoBuilder(temporary)._inject_go_config(
                temporary, 'some.host', 12000, 9000, 9001, 'test')
        if find_spec(loader_name):
            import_module(loader_name).GoLoaderBuilder(temporary)._inject_go_loader_config(
                temporary, 'some.host', 12000, 9000, 9001, 'test')
        py = (work / 'client/config/config.py').read_text()
        ast.parse(py)
        assert 'SERVER_FILE_TRANSFER_PORT = SERVER_WEB_PORT + 1' in py
        assert "'server_file_transfer_port'" not in py
        if find_spec(go_name):
            go = (work / 'client-go/config/config.go').read_text()
            assert 'SERVER_FILE_TRANSFER_PORT = SERVER_WEB_PORT + 1' in go
            assert 'strconv.Itoa(SERVER_FILE_TRANSFER_PORT)' in go
        if find_spec(loader_name):
            loader = (work / 'go-loader/config/config.go').read_text()
            assert 'ServerFileTransferPort = ServerWebPort + 1' in loader


def test_platform_api_reports_running_socket_and_web_ports():
    script = '''
import sys, types, json
stub=types.ModuleType("server.config.config")
stub.SOCKET_PORT=12000
stub.WEB_PORT=9000
sys.modules["server.config.config"] = stub
from server.application.web.agent_api import WebAgentApi
class Builder:
    def list_supported_builders(self):
        return ['bundle', 'go_loader']
api=WebAgentApi(Builder(), None)
print(json.dumps(api.get_server_platform()))
'''
    with tempfile.TemporaryDirectory() as temporary:
        result = subprocess.run([sys.executable,'-c',script], cwd=temporary,
                                env=dict(os.environ,PYTHONPATH=str(BACKEND)),capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['socket_port'] == 12000
    assert data['web_port'] == 9000
    assert data['builders'] == ['bundle', 'go_loader']
    assert 'file_transfer_port' not in data
