"""Saved Bind targets persist independently from machine identity and Settings."""
import sqlite3
from types import SimpleNamespace

import pytest

from server.application.connection.saved_bind_target_store import SavedBindTargetStore
from server.persistence.migrate_saved_bind_targets import migrate_file
from server.persistence.rch_database import RchDatabase


def _create(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    return db, SavedBindTargetStore(db)


def test_saved_targets_are_rows_and_independent_endpoints(tmp_path):
    db, store = _create(tmp_path)
    first = store.save('localhost', 9443, 'http://127.0.0.1:8085', name='Main')
    second = store.save('localhost', 9555, 'http://127.0.0.1:8085', name='Secondary')
    assert first['target_id'] != second['target_id']
    assert len(store.list_targets()) == 2
    assert db.connection().execute("SELECT COUNT(*) FROM settings WHERE namespace='saved_bind_targets'").fetchone()[0] == 0
    same = store.save('LOCALHOST', 9443, 'http://127.0.0.1:8085')
    assert same['target_id'] == first['target_id']
    assert same['name'] == 'Main'
    assert len(store.list_targets()) == 2
    db.close_thread_connection()


def test_target_machine_snapshot_does_not_change_endpoint_identity(tmp_path):
    db, store = _create(tmp_path)
    first = store.save('127.0.0.1', 9443, 'http://localhost:8085')
    second = store.save('127.0.0.1', 9555, 'http://localhost:8085')
    info = SimpleNamespace(client_id='last-bind-client', machine_id='same-machine', hostname='same-host', os_type='macOS',
                           os_ver='13', integrity='User')
    store.save('127.0.0.1', 9443, 'http://localhost:8085', session=SimpleNamespace(session_info=info))
    store.save('127.0.0.1', 9555, 'http://localhost:8085', session=SimpleNamespace(session_info=info))
    assert len(store.list_targets()) == 2
    assert {x['machine_id'] for x in store.list_targets()} == {'same-machine'}
    assert {x['target_id'] for x in store.list_targets()} == {first['target_id'], second['target_id']}
    assert {x['last_client_id'] for x in store.list_targets()} == {'last-bind-client'}
    db.close_thread_connection()


def test_edit_collision_remove_and_reopen(tmp_path):
    db, store = _create(tmp_path)
    first = store.save('example.org', 9443, 'https://server.test:443', name='A')
    second = store.save('example.org', 9555, 'https://server.test:443', name='B')
    with pytest.raises(ValueError, match='already uses'):
        store.save('EXAMPLE.ORG', 9555, 'https://server.test:443', name='A', target_id=first['target_id'])
    renamed = store.save('example.org', 9444, 'https://server.test:443', name='New A', target_id=first['target_id'])
    assert renamed['target_id'] == first['target_id'] and renamed['port'] == 9444
    db.close_thread_connection()
    reopened = RchDatabase(str(tmp_path / 'rch.db'))
    other = SavedBindTargetStore(reopened)
    assert {r['target_id'] for r in other.list_targets()} == {first['target_id'], second['target_id']}
    other.remove(first['target_id'])
    assert [r['target_id'] for r in other.list_targets()] == [second['target_id']]
    reopened.close_thread_connection()


def test_old_schema_migrates_without_touching_any_existing_record(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.connection().execute("INSERT INTO settings(namespace,value_json) VALUES ('protected', '{\"key\":1}')")
    db.close_thread_connection()
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE saved_bind_targets')
    migrated = RchDatabase(str(path))
    assert migrated.integrity_check() == 'ok'
    assert migrated.connection().execute("SELECT value_json FROM settings WHERE namespace='protected'").fetchone()[0] == '{"key":1}'
    assert SavedBindTargetStore(migrated).list_targets() == []
    migrated.close_thread_connection()
    migrated = RchDatabase(str(path))
    assert migrated.integrity_check() == 'ok'
    migrated.close_thread_connection()


def test_standalone_migration_creates_verifiable_backup(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.close_thread_connection()
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE saved_bind_targets')
        conn.execute("INSERT INTO settings(namespace,value_json) VALUES ('preserved', '{}')")
    destination, backup = migrate_file(path)
    assert destination == path
    assert backup.exists()
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='saved_bind_targets'").fetchone() is None
        assert conn.execute("SELECT value_json FROM settings WHERE namespace='preserved'").fetchone()[0] == '{}'
    db = RchDatabase(str(path))
    assert SavedBindTargetStore(db).list_targets() == []
    db.close_thread_connection()
    with pytest.raises(FileExistsError):
        migrate_file(path)


def test_saved_bind_target_preserves_last_client_for_offline_history(tmp_path):
    db, store = _create(tmp_path)
    old = store.save('127.0.0.1', 9443, 'http://localhost:8085', name='Office')
    assert old['last_client_id'] == ''
    info = SimpleNamespace(client_id='history-client-01', machine_id='machine-01',
                           hostname='office-mac', os_type='macOS', os_ver='14', integrity='User')
    live = store.save('127.0.0.1', 9443, 'http://localhost:8085', session=SimpleNamespace(session_info=info))
    assert live['last_client_id'] == 'history-client-01'
    assert live['name'] == 'Office'
    changed = store.save('127.0.0.1', 9443, 'http://localhost:8085', name='New name', target_id=old['target_id'])
    assert changed['last_client_id'] == 'history-client-01'
    db.close_thread_connection()
    reopened = RchDatabase(str(tmp_path / 'rch.db'))
    assert SavedBindTargetStore(reopened).list_targets()[0]['last_client_id'] == 'history-client-01'
    reopened.close_thread_connection()


def test_existing_v58_table_upgrades_in_place_and_preserves_targets(tmp_path):
    from server.persistence.rch_database import SAVED_BIND_TARGETS_SCHEMA

    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.close_thread_connection()
    # v58 table lacked last_client_id; preserve unique endpoint index and stored names.
    v58_schema = SAVED_BIND_TARGETS_SCHEMA.replace("                last_client_id TEXT NOT NULL DEFAULT '',\n", '')
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE saved_bind_targets')
        conn.execute(v58_schema)
        conn.execute('''INSERT INTO saved_bind_targets
            (target_id,host,port,server_web_base_url,name,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)''',
            ('target-01', 'localhost', 9443, 'http://localhost:8085', 'Keep name', 'now', 'now'))
    db = RchDatabase(str(path))
    stored = SavedBindTargetStore(db).list_targets()
    assert len(stored) == 1
    assert stored[0]['name'] == 'Keep name'
    assert stored[0]['last_client_id'] == ''
    assert db.integrity_check() == 'ok'
    db.close_thread_connection()


def test_v58_saved_targets_standalone_migration_backs_up_before_adding_history_id(tmp_path):
    from server.persistence.rch_database import SAVED_BIND_TARGETS_SCHEMA

    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.close_thread_connection()
    v58_schema = SAVED_BIND_TARGETS_SCHEMA.replace("                last_client_id TEXT NOT NULL DEFAULT '',\n", '')
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE saved_bind_targets')
        conn.execute(v58_schema)
        conn.execute('''INSERT INTO saved_bind_targets
            (target_id,host,port,server_web_base_url,name,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)''',
            ('old-target', '127.0.0.1', 9433, 'http://localhost:8085', 'Office', 'now', 'now'))
    destination, backup = migrate_file(path)
    assert destination == path and backup.is_file()
    with sqlite3.connect(backup) as conn:
        assert 'last_client_id' not in [r[1] for r in conn.execute('PRAGMA table_info(saved_bind_targets)')]
        assert conn.execute("SELECT name FROM saved_bind_targets WHERE target_id='old-target'").fetchone()[0] == 'Office'
    db = RchDatabase(str(path))
    assert SavedBindTargetStore(db).list_targets()[0]['last_client_id'] == ''
    db.close_thread_connection()
