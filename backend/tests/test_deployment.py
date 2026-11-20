"""Client bundles, update transport and operational recovery."""

import ast
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from client.commands.shell.standalone import update as update_ops
from server.application.agent.agent_builder import AgentBuilder
from server.application.connection.control_command_store import ControlCommandStore
from server.application.scripts.script_catalog_service import ScriptCatalogService


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


def test_explicit_bundle_generates_valid_source_zip():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _stub_bundle_root(root)
        agent = _agent(root)
        with patch('server.application.agent.agent_build_utils.build_client_revision_manifest',
                   return_value={'revision': 'abc', 'parts': {}, 'files': {}}):
            result = agent.build_agent('host.example', 9999, 8085, builder='python')
        assert result['builder'] == 'python'
        with zipfile.ZipFile(result['file_path']) as z:
            assert 'client/config/config.py' in z.namelist()
            config = ast.parse(z.read('client/config/config.py').decode())
            assignments = {
                node.targets[0].id: node.value
                for node in config.body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            }
            assert ast.literal_eval(assignments['SERVER_WEB_PORT']) == 8085
            assert 'rchclient.py' in z.namelist()
            assert all(not n.startswith('server/') for n in z.namelist())


def test_update_payload_preserves_pinned_tls(monkeypatch):
    fp = 'a' * 64
    monkeypatch.setattr(update_ops, 'RUNTIME_CONFIG', {'server_transport': 'tls_tcp', 'server_tls_fingerprint': fp})
    data = update_ops._build_update_request_payload()
    assert data['source'] == 'update'
    assert data['server_transport'] == 'tls_tcp'
    assert data['server_tls_fingerprint'] == fp


def test_update_preserves_existing_release_and_discards_failed_staging(tmp_path):
    archive = tmp_path / 'bundle.zip'
    target = tmp_path / 'release'
    target.mkdir()
    previous = target / 'keep.txt'
    previous.write_text('other update')
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('rchclient.py', 'ready')

    with pytest.raises(FileExistsError, match='Incomplete release already exists'):
        update_ops._extract_update_bundle_safely(str(archive), str(target))
    assert previous.read_text() == 'other update'

    entry = target / 'rchclient.py'
    entry.write_text('existing release')
    assert update_ops._extract_update_bundle_safely(str(archive), str(target)) == str(target)
    assert entry.read_text() == 'existing release'

    fresh = tmp_path / 'fresh'
    assert update_ops._extract_update_bundle_safely(str(archive), str(fresh)) == str(fresh)
    assert (fresh / 'rchclient.py').read_text() == 'ready'

    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('partial.txt', 'downloaded')
    with pytest.raises(FileNotFoundError, match='rchclient.py not found after extract'):
        update_ops._extract_update_bundle_safely(str(archive), str(tmp_path / 'new'))
    assert sorted(path.name for path in tmp_path.iterdir()) == ['bundle.zip', 'fresh', 'release']


def test_resume_failure_ack_and_wrong_client_rejected():
    store = ControlCommandStore()
    request = store.set_pending_command('paused-original', 'resume')
    with pytest.raises(ValueError, match='not been received'):
        store.acknowledge_control('paused-original', request['command_id'], 'delivered')
    store.pop_pending_command('paused-original')
    with pytest.raises(ValueError, match='Unknown'):
        store.acknowledge_control('another-client', request['command_id'], 'delivered')
    outcome = store.acknowledge_control('paused-original', request['command_id'], 'failed', 'IPC unavailable')
    assert outcome['status'] == 'failed'
    assert outcome['detail'] == 'IPC unavailable'


def test_script_rename_replace_failure_restores_old_file(tmp_path, monkeypatch):
    service = ScriptCatalogService(str(tmp_path))
    content = 'SCRIPT_METADATA = {"name": "old"}\n'
    service.save_script('old', content)
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        service.rename_script('old', 'new')
    assert service.get_script_content('old') == content
    assert not (tmp_path / 'new.py').exists()
    assert list(tmp_path.iterdir()) == [tmp_path / 'old.py']
