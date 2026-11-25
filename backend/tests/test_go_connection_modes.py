"""Go build parameters use Python's established Reverse/Bind transport contract."""
from pathlib import Path
import shutil
import subprocess

import pytest

from server.application.agent.agent_build_client_go import ClientGoBuilder
from server.application.agent.agent_build_go_loader import GoLoaderBuilder
from server.runtime.listener_protocols import get_listener_protocol


@pytest.fixture
def go_source(tmp_path):
    root = Path(__file__).parents[1]
    for name in ('client-go', 'go-loader'):
        shutil.copytree(root / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize('mode', ('reverse', 'bind'))
@pytest.mark.parametrize('transport', ('tcp', 'mtls_tcp'))
def test_go_client_build_settings(go_source, mode, transport):
    builder = ClientGoBuilder(str(go_source))
    builder._inject_go_config(str(go_source), '192.0.2.20' if mode == 'reverse' else '',
                              19443, 8085, 'test', listener_protocol=transport,
                              connection_mode=mode, bind_host='0.0.0.0', bind_port=19445)
    content = (go_source / 'client-go/config/config.go').read_text()
    assert f'var SERVER_TRANSPORT = "{transport}"' in content
    assert f'var CONNECTION_MODE = "{mode}"' in content
    assert 'var BIND_PORT = 19445' in content
    assert 'SERVER_TLS_FINGERPRINT' not in content
    assert 'var IDENTITY_DIR = ""' in content
    assert 'client_bundle' not in content  # User identity is resolved at runtime.
    if shutil.which('go'):
        subprocess.run(['go', 'build', '-o', str(go_source / 'build-client'), '.'],
                       cwd=go_source / 'client-go', check=True, capture_output=True, timeout=90)


@pytest.mark.parametrize('mode', ('reverse', 'bind'))
@pytest.mark.parametrize('transport', ('tcp', 'mtls_tcp'))
def test_go_loader_build_settings(go_source, mode, transport):
    builder = GoLoaderBuilder(str(go_source))
    builder._inject_go_loader_config(str(go_source), '192.0.2.20' if mode == 'reverse' else '',
                                     19443, 8085, 'test', server_web_host='192.0.2.5',
                                     listener_id='listener-abc' if mode == 'reverse' else '',
                                     listener_protocol=transport, connection_mode=mode,
                                     bind_host='0.0.0.0', bind_port=19445)
    content = (go_source / 'go-loader/config/config.go').read_text()
    assert f'const ConnectionMode = "{mode}"' in content
    assert f'const ServerTransport = "{transport}"' in content
    assert 'const BindPort = 19445' in content
    assert 'const ServerWebHost = "192.0.2.5"' in content
    assert 'const ServerListenerID = ""' in content if mode == 'bind' else 'const ServerListenerID = "listener-abc"' in content
    if shutil.which('go'):
        subprocess.run(['go', 'build', '-o', str(go_source / 'build-loader'), '.'],
                       cwd=go_source / 'go-loader', check=True, capture_output=True, timeout=90)


def test_mtls_listener_accepts_go_builder():
    get_listener_protocol('mtls_tcp').validate_build('go')
    get_listener_protocol('mtls_tcp').validate_build('go_loader')
    with pytest.raises(ValueError, match='Unsupported listener protocol'):
        get_listener_protocol('tls_tcp')
