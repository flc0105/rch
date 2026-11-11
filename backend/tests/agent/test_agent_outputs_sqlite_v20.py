"""SQLite Agent outputs registry: immutable build snapshots and indexed cleanup."""
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from server.application.agent.agent_output_registry import AgentOutputRegistry
from server.persistence.rch_database import RchDatabase
from server.application.maintenance.server_cleanup_service import ServerCleanupService


def register(registry, path, *, source='manual', listener_id='listener-1', listener_name='Original Listener'):
    path.write_bytes(b'BINARY DATA')
    return registry.register_output(
        {'file_name': path.name, 'builder': 'go', 'build_version': 'go_20261110_183218_12345678',
         'target_os': 'mac', 'target_arch': 'arm64', 'warnings': ['temporary warning']},
        source=source,
        request_payload={'listener_id': listener_id, 'listener_name': listener_name,
                         'server_host': 'example.test', 'server_port': 8899,
                         'server_web_scheme': 'https', 'server_web_host': 'downloads.example.test',
                         'web_port': 8443},
    )


def test_registry_uses_sqlite_with_compact_columns(tmp_path):
    registry = AgentOutputRegistry(str(tmp_path), RchDatabase(str(tmp_path / 'rch.db')))
    result = register(registry, tmp_path / 'rchclient_go_mac_arm64')
    assert result['build_time'] and result['size'] == 11
    assert result['listener_name'] == 'Original Listener'
    assert result['server_host'] == 'example.test'
    assert result['server_port'] == 8899
    assert result['server_web_host'] == 'downloads.example.test'
    assert result['server_web_scheme'] == 'https'
    assert result['web_port'] == 8443
    assert result['source'] == 'manual'
    assert not (tmp_path / '.metadata').exists()

    with sqlite3.connect(registry.database.db_path) as conn:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(agent_outputs)')}
        assert {'created_at', 'listener_name_snapshot', 'connect_host', 'connect_port',
                'web_scheme', 'web_host', 'web_port', 'source', 'listener_id'} <= columns
        assert not {'size', 'warnings', 'build_time', 'updated_at', 'listener_name', 'server_host'} & columns
        assert conn.execute('SELECT COUNT(*) FROM agent_outputs').fetchone()[0] == 1

    again = AgentOutputRegistry(str(tmp_path), RchDatabase(str(tmp_path / 'rch.db')))
    assert again.list_outputs()[0]['file_name'] == 'rchclient_go_mac_arm64'
    assert again.get_output_record('rchclient_go_mac_arm64')['size'] == 11
    (tmp_path / 'rchclient_go_mac_arm64').write_bytes(b'NEW')
    assert again.get_output_record('rchclient_go_mac_arm64')['size'] == 3


def test_only_indexed_outputs_are_listed_and_deleted(tmp_path):
    registry = AgentOutputRegistry(str(tmp_path), RchDatabase(str(tmp_path / 'rch.db')))
    (tmp_path / 'unindexed.zip').write_bytes(b'untracked')
    (tmp_path / '.metadata').mkdir()
    (tmp_path / '.metadata' / 'unindexed.zip.json').write_text('{}')
    assert registry.list_outputs() == []
    with pytest.raises(FileNotFoundError):
        registry.get_output_record('unindexed.zip')
    with pytest.raises(ValueError):
        registry.get_output_record('../other.zip')

    register(registry, tmp_path / 'registered.zip')
    assert len(registry.list_outputs()) == 1
    assert registry.delete_output('registered.zip') == {'deleted': True, 'file_name': 'registered.zip'}
    assert not (tmp_path / 'registered.zip').exists()
    assert not registry.list_outputs()
    assert (tmp_path / 'unindexed.zip').is_file()


def test_list_uses_current_listener_name_with_deleted_snapshot_fallback(tmp_path):
    registry = AgentOutputRegistry(str(tmp_path), RchDatabase(str(tmp_path / 'rch.db')))
    register(registry, tmp_path / 'one.zip')
    config = {'name': 'Renamed Listener'}
    class Listener:
        def get(self, listener_id):
            assert listener_id == 'listener-1'
            if config is None:
                raise ValueError('Unknown listener')
            return config
    # WebApi is loaded lazily; local test runner may omit optional Flask/Werkzeug.
    try:
        from server.application.web.agent_api import WebAgentApi
    except ModuleNotFoundError as exc:
        if exc.name in {'werkzeug', 'flask'}:
            pytest.skip('Web HTTP dependencies are not installed')
        raise
    api = WebAgentApi(SimpleNamespace(output_dir=str(tmp_path)), registry,
                      server=SimpleNamespace(listener_manager=Listener()))
    rows = api.list_agent_outputs()
    assert rows[0]['listener_name'] == 'Renamed Listener'
    assert rows[0]['server_host'] == 'example.test'  # build-time snapshot
    config = None
    assert api.list_agent_outputs()[0]['listener_name'] == 'Original Listener'


def test_cleanup_deletes_transient_rows_and_files_without_sidecar(tmp_path):
    registry = AgentOutputRegistry(str(tmp_path), RchDatabase(str(tmp_path / 'rch.db')))
    register(registry, tmp_path / 'bootstrap.zip', source='bootstrap')
    register(registry, tmp_path / 'manual.zip', source='manual')
    cleanup = ServerCleanupService.__new__(ServerCleanupService)
    cleanup.agent_output_registry = registry
    selected = cleanup._snapshot_agent_transient_outputs()
    assert selected == ['bootstrap.zip']
    result = cleanup._cleanup_agent_transient_outputs(selected)
    assert result['removed_files'] == 1
    assert result['bytes_freed'] == 11
    assert len(registry.list_outputs()) == 1
    assert registry.list_outputs()[0]['file_name'] == 'manual.zip'
    assert not (tmp_path / 'bootstrap.zip').exists()
