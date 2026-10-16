"""Registry-driven independent Agent builders and explicit build selection."""
import ast
import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from server.application.agent.agent_builder import AgentBuilder, AGENT_BUILDERS
from server.application.agent.agent_build_utils import copy_source_paths


def _agent(root: Path) -> AgentBuilder:
    agent = AgentBuilder.__new__(AgentBuilder)
    agent.source_dir = str(root)
    agent.output_dir = str(root / 'output')
    agent._ensure_dirs()
    return agent


def _stub_bundle_root(root: Path):
    (root / 'client/config').mkdir(parents=True)
    (root / 'core').mkdir()
    (root / 'rchclient.py').write_text('print("hello")')
    (root / 'client/config/config.py').write_text('original')
    (root / 'core/core.py').write_text('x=1')


def test_all_registered_builders_are_classes_with_same_build_method():
    for name, (module, class_name, kind_text) in AGENT_BUILDERS.items():
        assert name and kind_text
        loaded = importlib.import_module(module)
        instance = getattr(loaded, class_name)('/tmp')
        assert hasattr(instance, 'build') and callable(instance.build)
        assert not class_name.endswith('Plugin')


def test_builder_is_required_at_service_layer():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(Path(tmp))
        for kwargs in ({}, {'builder': None}, {'builder': ''}, {'builder': '   '}):
            with pytest.raises(ValueError, match='builder is required'):
                agent.build_agent('host.example', 9999, 8085, **kwargs)


def test_explicit_bundle_generates_valid_source_zip():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _stub_bundle_root(root)
        agent = _agent(root)
        with patch('server.application.agent.agent_build_utils.build_client_revision_manifest',
                   return_value={'revision': 'abc', 'parts': {}, 'files': {}}):
            result = agent.build_agent('host.example', 9999, 8085, builder='bundle')
        assert result['builder'] == 'bundle'
        assert result['target_os'] == 'bundle'
        assert result['file_name'].startswith('rchclient-source-bundle-')
        with zipfile.ZipFile(result['file_path']) as z:
            assert 'client/config/config.py' in z.namelist()
            cfg = z.read('client/config/config.py').decode()
            ast.parse(cfg)
            assert 'SERVER_FILE_TRANSFER_PORT = SERVER_WEB_PORT + 1' in cfg
            assert 'SERVER_WEB_PORT = 8085' in cfg
            assert 'rchclient.py' in z.namelist()
            assert all(not n.startswith('server/') for n in z.namelist())


def test_registry_can_disable_bundle_without_removing_source():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(Path(tmp))
        with patch.dict(AGENT_BUILDERS, {}, clear=True):
            assert agent.list_supported_builders() == []
            assert agent.SUPPORTED_BUILDERS == set()
            with pytest.raises(ValueError, match='Unsupported builder: bundle'):
                agent.build_agent('host', 9999, 8085, builder='bundle')
        with patch.dict(AGENT_BUILDERS, {k: v for k,v in AGENT_BUILDERS.items() if k != 'bundle'}, clear=True):
            assert 'bundle' not in agent.list_supported_builders()
            assert 'go_loader' in agent.list_supported_builders()
        assert importlib.util.find_spec('server.application.agent.agent_build_bundle') is not None


def test_registry_removing_other_modes_does_not_change_bundle():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _agent(Path(tmp))
        with patch.dict(AGENT_BUILDERS, {'bundle': AGENT_BUILDERS['bundle']}, clear=True):
            assert agent.list_supported_builders() == ['bundle']
        assert agent.list_supported_builders() == list(AGENT_BUILDERS)


@pytest.mark.parametrize('kind,module_name,class_name,kind_text', [
    (k, *v) for k,v in AGENT_BUILDERS.items()
])
def test_each_mode_dispatches_to_its_class(kind, module_name, class_name, kind_text):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        agent = _agent(root)
        cls = getattr(importlib.import_module(module_name), class_name)
        def stub(self, **kwargs):
            assert self.source_dir == str(root)
            assert kwargs['file_transfer_port'] == 9001
            dest = Path(kwargs['work_dir']) / 'artifact'
            dest.write_text('test')
            return {'file_path': str(dest), 'file_name': 'artifact', 'target_os': kind}
        with patch.object(cls, 'build', stub):
            result = agent.build_agent('example', 9999, 9000, builder=kind,
                                       target_os='linux', target_arch='amd64')
        assert result['builder'] == kind
        assert Path(result['file_path']).read_text() == 'test'
        assert result['build_version'].startswith(kind_text + '-')


def test_pyinstaller_rejects_cross_platform_without_launching_executable():
    from server.application.agent.agent_build_pyinstaller import PyInstallerBuilder
    with tempfile.TemporaryDirectory() as tmp:
        builder = PyInstallerBuilder(tmp)
        with patch.object(builder, '_get_current_pyinstaller_target', return_value='mac'):
            with pytest.raises(ValueError, match='same platform'):
                builder._build_with_pyinstaller(tmp, 'server', 9999, 8085, 8086, 'win')


@pytest.mark.parametrize('module_name,class_name,folder,filename,expected', [
    ('server.application.agent.agent_build_client_go','ClientGoBuilder','client-go','rchclient-go-client-linux-amd64-id','SERVER_FILE_TRANSFER_PORT = SERVER_WEB_PORT + 1'),
    ('server.application.agent.agent_build_go_loader','GoLoaderBuilder','go-loader','rchclient-go-loader-linux-amd64-id','ServerFileTransferPort = ServerWebPort + 1'),
])
def test_go_builders_remain_independent(module_name, class_name, folder, filename, expected):
    builder_class = getattr(importlib.import_module(module_name), class_name)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/folder/'config').mkdir(parents=True)
        (root/folder/'config'/'config.go').write_text('original')
        builder = builder_class(str(root))
        calls=[]
        def fake_go(cwd,path,os_name,arch):
            calls.append((os_name,arch))
            Path(path).write_bytes(b'go-binary')
        with patch.object(builder,'_run_go_build',side_effect=fake_go):
            method = builder._build_with_go_loader if folder == 'go-loader' else builder._build_with_go
            result=method(str(root/'stage'),'host',9999,8085,8086,'linux','amd64','id','build-id')
        assert result['file_name'] == filename
        assert result['target_arch'] == 'amd64'
        assert calls == [('linux','amd64')]
        assert expected in (root/'stage'/'rat'/folder/'config'/'config.go').read_text()


def test_discovery_skips_missing_module_at_runtime():
    import server.application.agent.agent_builder as reg
    b = AgentBuilder.__new__(AgentBuilder)
    original = importlib.util.find_spec
    with patch.object(reg.importlib.util, 'find_spec', side_effect=lambda name: None if name.endswith('agent_build_bundle') else original(name)):
        assert 'bundle' not in b.list_supported_builders()
        assert 'go_loader' in b.list_supported_builders()
