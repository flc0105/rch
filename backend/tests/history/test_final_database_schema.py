"""Final runtime database structure has one canonical, non-migrating contract."""

import sqlite3

import pytest

from server.persistence.rch_database import RchDatabase


def _tables(connection):
    return {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_new_database_creates_only_final_tables_and_indexes(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    conn = db.connection()
    assert len(_tables(conn)) == 14
    assert 'schema_migrations' not in _tables(conn)
    assert 'snapshot_json' in {row[1] for row in conn.execute('PRAGMA table_info(background_job_files)')}
    assert 'termination_detail_json' in {row[1] for row in conn.execute('PRAGMA table_info(connection_sessions)')}
    assert len(list(conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"))) == 16
    assert db.integrity_check() == 'ok'
    db.close_thread_connection()
    reopened = RchDatabase(str(tmp_path / 'rch.db'))
    assert reopened.integrity_check() == 'ok'
    reopened.close_thread_connection()


def test_existing_final_database_preserves_data_and_unrelated_tables(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.connection().execute("INSERT INTO settings(namespace,value_json) VALUES ('test', '{\"ok\":true}')")
    db.connection().execute('CREATE TABLE external_app_table (value TEXT)')
    db.connection().execute("INSERT INTO external_app_table VALUES ('retained')")
    db.close_thread_connection()
    reopened = RchDatabase(str(path))
    assert reopened.connection().execute("SELECT value_json FROM settings WHERE namespace='test'").fetchone()[0] == '{"ok":true}'
    assert reopened.connection().execute('SELECT value FROM external_app_table').fetchone()[0] == 'retained'
    reopened.close_thread_connection()


def test_database_rejects_retired_schema_metadata_without_modification(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.connection().execute("INSERT INTO settings(namespace,value_json) VALUES ('keep', '123')")
    db.connection().execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
    db.close_thread_connection()
    with pytest.raises(RuntimeError, match='retired schema metadata'):
        RchDatabase(str(path))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value_json FROM settings WHERE namespace='keep'").fetchone()[0] == '123'
        conn.execute('DROP TABLE schema_migrations')
    reopened = RchDatabase(str(path))
    assert reopened.connection().execute("SELECT value_json FROM settings WHERE namespace='keep'").fetchone()[0] == '123'
    reopened.close_thread_connection()


def test_database_rejects_existing_schema_with_unexpected_columns(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.close_thread_connection()
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE connection_sessions ADD COLUMN obsolete_column TEXT DEFAULT ''")
    with pytest.raises(RuntimeError, match='incompatible schema'):
        RchDatabase(str(path))
