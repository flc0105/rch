"""Artifact and Agent Output metadata share the canonical rch.db connection and schema."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from server.application.agent.agent_output_registry import AgentOutputRegistry
from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.persistence.rch_database import RchDatabase


def _artifact(path, identifier):
    path.write_bytes(b'artifact contents')
    return {
        'artifact_id': identifier,
        'scope': 'saved',
        'category': 'screenshots',
        'machine_id': 'machine-a',
        'saved_path': str(path),
        'saved_at': '2026-11-11 10:00:00',
        'original_name': path.name,
    }


def _build(registry, path):
    path.write_bytes(b'binary contents')
    return registry.register_output(
        {'file_name': path.name, 'builder': 'go_loader', 'build_version': 'v1'},
        request_payload={'listener_id': 'listener-a', 'listener_name': 'Primary'},
    )


def test_unified_database_roundtrip_and_online_backup_keep_files_on_disk(tmp_path):
    root = tmp_path / 'runtime'
    root.mkdir()
    db = RchDatabase(str(root / 'rch.db'))
    artifact_dir = root / 'web_files' / 'artifacts'
    output_dir = root / 'agent_output'
    artifact_dir.mkdir(parents=True)
    catalog = ArtifactSqliteCatalog(db)
    registry = AgentOutputRegistry(str(output_dir), db)

    catalog.save(_artifact(artifact_dir / 'image.png', 'artifact-1'))
    _build(registry, output_dir / 'agent.exe')
    db.connection().execute("INSERT INTO settings(namespace, value_json) VALUES ('test', '{}')")
    assert catalog.get('artifact-1')['folder_id'] == 'saved:screenshots'
    assert registry.get_output_record('agent.exe')['listener_name'] == 'Primary'
    assert not (artifact_dir / 'catalog.sqlite3').exists()
    assert not (output_dir / 'agent_outputs.sqlite3').exists()

    backup = tmp_path / 'snapshot.db'
    db.backup(str(backup))
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT category FROM artifact_entries').fetchone()[0] == 'screenshots'
        assert conn.execute('SELECT file_name FROM agent_outputs').fetchone()[0] == 'agent.exe'
        assert conn.execute('SELECT value_json FROM settings').fetchone()[0] == '{}'
        assert conn.execute('SELECT COUNT(*) FROM artifact_folders').fetchone()[0] == 9
    assert (artifact_dir / 'image.png').read_bytes() == b'artifact contents'
    assert (output_dir / 'agent.exe').read_bytes() == b'binary contents'
    assert db.integrity_check() == 'ok'
    db.close_thread_connection()

    reopened = RchDatabase(str(root / 'rch.db'))
    assert ArtifactSqliteCatalog(reopened).get('artifact-1')['category'] == 'screenshots'
    assert AgentOutputRegistry(str(output_dir), reopened).list_outputs()[0]['file_name'] == 'agent.exe'
    reopened.close_thread_connection()


def test_unified_database_transactions_preserve_other_business_rows(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    catalog = ArtifactSqliteCatalog(db)
    registry = AgentOutputRegistry(str(tmp_path / 'outputs'), db)
    _build(registry, tmp_path / 'outputs' / 'first.zip')
    db.connection().execute("INSERT INTO settings(namespace, value_json) VALUES ('keep', '42')")
    good = _artifact(tmp_path / 'good.png', 'good')
    bad = _artifact(tmp_path / 'bad.png', 'bad')
    bad['folder_id'] = 'saved:downloads'
    with pytest.raises(ValueError, match='must match category'):
        catalog.import_records([good, bad])
    assert catalog.get('good') is None
    assert registry.list_outputs()[0]['file_name'] == 'first.zip'
    assert db.connection().execute("SELECT value_json FROM settings WHERE namespace='keep'").fetchone()[0] == '42'
    db.close_thread_connection()


def test_unified_database_rejects_missing_tables_without_recreating_them(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.close_thread_connection()
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE artifact_entries')
        conn.execute('DROP TABLE artifact_folders')
        conn.execute('DROP TABLE agent_outputs')
    with pytest.raises(RuntimeError, match='incompatible schema for'):
        RchDatabase(str(path))
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {'artifact_entries', 'artifact_folders', 'agent_outputs'} & tables


def test_concurrent_artifact_and_agent_writes_share_thread_scoped_connections(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    catalog = ArtifactSqliteCatalog(db)
    output_dir = tmp_path / 'outputs'
    registry = AgentOutputRegistry(str(output_dir), db)

    def worker(index):
        try:
            catalog.save(_artifact(tmp_path / f'art-{index}.txt', f'art-{index}'))
            _build(registry, output_dir / f'build-{index}.zip')
            return catalog.get(f'art-{index}')['artifact_id']
        finally:
            db.close_thread_connection()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(worker, range(8))) == [f'art-{i}' for i in range(8)]
    assert len(catalog.list(scope='saved')) == 8
    assert len(registry.list_outputs()) == 8
    assert db.integrity_check() == 'ok'
    db.close_thread_connection()
