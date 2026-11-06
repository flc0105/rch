"""Go (Simple) Agent Builder uses selected TCP or pinned TLS listener."""
import importlib
import os
import sys
import types
from pathlib import Path

import pytest

from server.application.agent.agent_build_client_go import ClientGoBuilder
from server.runtime.listener_protocols import get_listener_protocol


def test_go_client_registered_and_tls_listener_allows_it():
    source = Path(__file__).resolve().parents[2] / 'server/application/agent/agent_builder.py'
    assert "'go': ('server.application.agent.agent_build_client_go'" in source.read_text()
    tls = get_listener_protocol('tls_tcp')
    assert 'go' in tls.describe()['supported_builders']
    tls.validate_build('go', 'a' * 64)
    with pytest.raises(ValueError, match='pinned server certificate'):
        tls.validate_build('go', '')


@pytest.mark.parametrize('transport,pin', [
    ('tcp', ''),
    ('tls_tcp', 'e' * 64),
])
def test_builder_injects_transport_and_fingerprint(tmp_path, monkeypatch, transport, pin):
    source = tmp_path / 'source'
    source_config = source / 'client-go' / 'config'
    source_config.mkdir(parents=True)
    (source_config / 'config.go').write_text('package config\n', encoding='utf-8')
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    calls = []

    def fake_go(cwd, output_path, goos, goarch):
        calls.append((cwd, output_path, goos, goarch))
        Path(output_path).write_bytes(b'build output')

    monkeypatch.setattr('server.application.agent.agent_build_client_go.run_go_build', fake_go)
    result = ClientGoBuilder(str(source)).build(
        work_dir=str(work_dir), server_host='test.example', server_port=9443,
        web_port=8085, target_os='mac', target_arch='arm64',
        build_id='test', build_version='v1',
        listener_protocol=transport, tls_fingerprint=pin,
    )
    text = (work_dir / 'rat' / 'client-go' / 'config' / 'config.go').read_text()
    assert f'var SERVER_TRANSPORT = "{transport}"' in text
    assert f'var SERVER_TLS_FINGERPRINT = "{pin}"' in text
    assert 'var SERVER_ADDR = "test.example:9443"' in text
    assert result['file_name'].endswith('-mac-arm64-test')
    assert len(calls) == 1 and calls[0][2:] == ('darwin', 'arm64')


def test_agent_build_dispatch_passes_selected_tls_settings(tmp_path, monkeypatch):
    # The AgentBuilder runtime config imports Flask/Werkzeug, which are not
    # installed in the isolated Go builder test environment.
    config_module = types.ModuleType('server.config.config')
    config_module.SERVER_RUNTIME_DIR = str(tmp_path / 'runtime')
    with monkeypatch.context() as patcher:
        patcher.setitem(sys.modules, 'server.config.config', config_module)
        sys.modules.pop('server.application.agent.agent_builder', None)
        try:
            module = importlib.import_module('server.application.agent.agent_builder')
            AgentBuilder = module.AgentBuilder
        finally:
            sys.modules.pop('server.application.agent.agent_builder', None)
    agent = AgentBuilder.__new__(AgentBuilder)
    agent.source_dir = str(tmp_path)
    agent.output_dir = str(tmp_path / 'output')
    os.makedirs(agent.output_dir)
    args = {}

    def fake_build(self, **kwargs):
        args.update(kwargs)
        filename = 'client-go-test'
        path = Path(kwargs['work_dir']) / filename
        path.write_bytes(b'compiled client')
        return {'file_path': str(path), 'file_name': filename, 'warnings': [], 'target_os': 'mac', 'target_arch': 'arm64'}

    monkeypatch.setattr(ClientGoBuilder, 'build', fake_build)
    result = agent.build_agent('test.example', 9443, 8085, builder='go',
                               target_os='mac', target_arch='arm64',
                               listener_protocol='tls_tcp', tls_fingerprint='a' * 64)
    assert result['builder'] == 'go'
    assert args['listener_protocol'] == 'tls_tcp'
    assert args['tls_fingerprint'] == 'a' * 64
    assert (Path(agent.output_dir) / 'client-go-test').is_file()
