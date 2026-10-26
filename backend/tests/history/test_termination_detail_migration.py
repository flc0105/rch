"""Standalone SQLite migration keeps connection history data and statuses intact."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from server.persistence.rch_database import RchDatabase


MIGRATION_PATH = Path(__file__).resolve().parents[2] / 'tools' / 'migrate_connection_session_columns.py'
spec = importlib.util.spec_from_file_location('connection_column_migration', MIGRATION_PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def _seed_db(path):
    db = RchDatabase(str(path))
    db.close_thread_connection()
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated_data (value TEXT)")
        conn.execute("INSERT INTO unrelated_data VALUES ('keep me')")
        conn.executemany('''INSERT INTO connection_sessions(
            machine_id, client_id, connected_at, disconnected_at,
            connection_state, disconnect_reason, termination_reason, termination_detail_json
        ) VALUES (?, ?, '2026-10-26T10:00:00', '2026-10-26T10:00:01', ?, ?, ?, ?)''', [
            ('m', 'aborted', 'offline', 'disconnected', 'connection_lost', json.dumps({'summary': 'EOF'})),
            ('m', 'manual', 'offline', 'disconnected', 'server_requested_disconnect', json.dumps({'command': 'httpctl kill'})),
        ])


@pytest.mark.parametrize('old_column', ['error_diagnostics_json', 'detail_json'])
def test_migration_from_prior_detail_columns_preserves_json_and_normalizes_status(tmp_path, old_column):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f'ALTER TABLE connection_sessions RENAME COLUMN termination_detail_json TO {old_column}')
    backup = migration.migrate(db_path)
    assert backup.exists()
    with sqlite3.connect(db_path) as conn:
        columns = migration.table_columns(conn)
        assert 'termination_detail_json' in columns and old_column not in columns
        rows = list(conn.execute('SELECT client_id, connection_state, disconnect_reason, termination_detail_json FROM connection_sessions ORDER BY client_id'))
        assert rows[0] == ('aborted', 'interrupted', 'interrupted', '{"summary": "EOF"}')
        assert rows[1] == ('manual', 'offline', 'disconnected', '{"command": "httpctl kill"}')
        assert conn.execute('SELECT value FROM unrelated_data').fetchone()[0] == 'keep me'
    with sqlite3.connect(backup) as conn:
        assert 'termination_detail_json' not in migration.table_columns(conn)
    assert migration.migrate(db_path) is None
    RchDatabase(str(db_path)).close_thread_connection()


def test_migration_from_original_reason_and_detail_columns(tmp_path):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute('ALTER TABLE connection_sessions RENAME COLUMN termination_reason TO reason')
        conn.execute('ALTER TABLE connection_sessions RENAME COLUMN termination_detail_json TO detail_json')
    assert migration.migrate(db_path)
    with sqlite3.connect(db_path) as conn:
        assert {'termination_reason', 'termination_detail_json'} <= migration.table_columns(conn)
        assert 'reason' not in migration.table_columns(conn)
        assert conn.execute("SELECT connection_state FROM connection_sessions WHERE client_id='aborted'").fetchone()[0] == 'interrupted'


def test_canonical_columns_with_old_offline_abnormal_rows_are_normalized(tmp_path):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    assert migration.migrate(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT connection_state FROM connection_sessions WHERE client_id='aborted'").fetchone()[0] == 'interrupted'
    assert migration.migrate(db_path) is None


def test_migration_can_add_columns_to_older_database(tmp_path):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute('ALTER TABLE connection_sessions DROP COLUMN termination_reason')
        conn.execute('ALTER TABLE connection_sessions DROP COLUMN termination_detail_json')
    assert migration.migrate(db_path)
    with sqlite3.connect(db_path) as conn:
        assert {'termination_reason', 'termination_detail_json'} <= migration.table_columns(conn)
        assert conn.execute('SELECT COUNT(*) FROM connection_sessions').fetchone()[0] == 2


def test_migration_rejects_conflicting_data_without_changes(tmp_path):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE connection_sessions ADD COLUMN error_diagnostics_json TEXT DEFAULT '{}' ")
    with pytest.raises(RuntimeError, match='Conflicting columns'):
        migration.migrate(db_path)
    with sqlite3.connect(db_path) as conn:
        assert 'error_diagnostics_json' in migration.table_columns(conn)


def test_migration_dry_run_keeps_schema_and_old_state(tmp_path):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute('ALTER TABLE connection_sessions RENAME COLUMN termination_detail_json TO error_diagnostics_json')
    assert migration.migrate(db_path, dry_run=True) is None
    with sqlite3.connect(db_path) as conn:
        assert 'error_diagnostics_json' in migration.table_columns(conn)
        assert conn.execute("SELECT connection_state FROM connection_sessions WHERE client_id='aborted'").fetchone()[0] == 'offline'


def test_wal_committed_data_survives_backup(tmp_path):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    writer = sqlite3.connect(db_path)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('INSERT INTO unrelated_data VALUES (?)', ('wal data',))
        writer.commit()
        writer.close()
        backup = migration.migrate(db_path)
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT COUNT(*) FROM unrelated_data WHERE value='wal data'").fetchone()[0] == 1
    finally:
        try:
            writer.close()
        except Exception:
            pass


def test_failed_sql_update_rolls_back_column_rename_and_state_change(tmp_path, monkeypatch):
    db_path = tmp_path / 'rch.db'
    _seed_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute('ALTER TABLE connection_sessions RENAME COLUMN termination_detail_json TO error_diagnostics_json')

    def reject_update(connection):
        raise RuntimeError('injected failure after ALTER TABLE')

    monkeypatch.setattr(migration, 'normalize_abnormal_states', reject_update)
    with pytest.raises(RuntimeError, match='injected failure'):
        migration.migrate(db_path)

    with sqlite3.connect(db_path) as conn:
        cols = migration.table_columns(conn)
        assert 'error_diagnostics_json' in cols
        assert 'termination_detail_json' not in cols
        assert conn.execute("SELECT connection_state FROM connection_sessions WHERE client_id='aborted'").fetchone()[0] == 'offline'
    assert len(list(tmp_path.glob('rch.db.before-termination-columns-*.bak'))) == 1
