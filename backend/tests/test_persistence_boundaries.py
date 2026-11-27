"""Canonical database startup, composable SQL transactions and Store boundaries."""
import ast
import sqlite3
import sys
import threading
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from server.application.connection.connection_history_store import ConnectionHistoryStore
from server.application.connection.recent_device_store import RecentDeviceStore
from server.application.history.pinned_command_store import PinnedCommandStore
from server.application.jobs.background_job_service import BackgroundJobService
from server.application.jobs.background_job_store import BackgroundJobStore
from server.application.pinned_paths.pinned_path_store import PinnedPathStore
from server.application.preferences.settings_store import SettingsStore
from server.application.transfers.transfer_history_store import TransferHistoryStore
from server.persistence.rch_database import RchDatabase


TABLES = {
    'activity_records', 'agent_outputs', 'artifact_entries', 'artifact_folders',
    'background_job_files', 'background_job_messages', 'background_jobs',
    'command_recents', 'connection_sessions', 'device_group_members',
    'device_groups', 'external_tool_presets', 'keychain_entries', 'notifications',
    'pinned_commands', 'pinned_paths', 'recent_devices', 'saved_bind_targets', 'settings',
    'transfer_batches', 'transfer_records',
}


@pytest.fixture
def db(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    yield database
    database.close_thread_connection()


@pytest.fixture
def history_class():
    # Test the actual History Store without loading unrelated Web auth dependencies.
    config = types.ModuleType('server.config.config')
    config.COMMAND_HISTORY_MAX_RESULT_FIELD_BYTES = 256 * 1024
    config.COMMAND_HISTORY_PAGE_SIZE = 50
    config.COMMAND_HISTORY_MAX_PAGE_SIZE = 200
    config.COMMAND_HISTORY_RECENT_LIMIT = 100
    with patch.dict(sys.modules, {'server.config.config': config}):
        from server.application.history.history_store import CommandHistoryStore
        yield CommandHistoryStore


def table_names(db):
    return {row[0] for row in db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_base_schema_has_all_tables_and_domain_indexes_without_service_startup(db):
    assert table_names(db) == TABLES
    indexes = {row[0] for row in db.fetch_all("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {'idx_activity_machine_time', 'idx_activity_machine_status',
            'idx_activity_machine_kind', 'idx_activity_client_time',
            'uq_keychain_machine_name', 'idx_transfer_records_time'} <= indexes
    assert db.fetch_one('PRAGMA foreign_keys')[0] == 1
    assert db.fetch_one('PRAGMA journal_mode')[0] == 'wal'
    assert db.integrity_check() == 'ok'


def test_database_only_reopen_initializes_missing_domain_tables_without_changing_data(db):
    SettingsStore(db, 'retained').write({'value': 'keep'})
    # A database initialized without the former three module constructors had these absent.
    with db.transaction() as conn:
        for name in ('activity_records', 'keychain_entries', 'transfer_records'):
            conn.execute(f'DROP TABLE {name}')
    db.close_thread_connection()
    reopened = RchDatabase(db.db_path)
    assert table_names(reopened) == TABLES
    assert SettingsStore(reopened, 'retained').read() == {'value': 'keep'}
    assert reopened.integrity_check() == 'ok'
    reopened.close_thread_connection()


def create_activity(store, connection, entry_id, summary, *, status=None):
    store.write_service.create_activity_for_dispatch(connection, entry_id, {
        'kind': 'command', 'action': 'invoke', 'origin': 'web', 'presentation': 'none',
        'invocation': {'command': summary}, 'resolved': {}, 'summary': summary,
    })
    if status:
        store.update_entry_status_for_connection(connection, entry_id, status)


def connection(machine='machine', client='client'):
    return SimpleNamespace(session_info=SimpleNamespace(machine_id=machine, client_id=client))


def test_reopen_preserves_records_and_domain_recovery_is_separate(db, history_class, tmp_path):
    from server.application.keychains.keychain_store import KeychainStore
    history = history_class(db)
    create_activity(history, connection(), 'active', 'test')
    keys = KeychainStore(db, key_file_path=tmp_path / 'keychains.key')
    key = keys.create_item({'kind': 'secret', 'name': 'fixture', 'secret_value': 'test-only'})
    transfers = TransferHistoryStore(db)
    item = {name: '' for name in transfers.COLUMNS}
    item.update(transfer_id='x', state='running', direction='client_to_server',
                total_bytes=5, transferred_bytes=0, started_at='2026-01-01')
    transfers.record_started(item)
    db.close_thread_connection()
    reopened = RchDatabase(db.db_path)
    assert reopened.fetch_one("SELECT status FROM activity_records WHERE activity_id='active'")[0] == 'running'
    assert reopened.fetch_one("SELECT state FROM transfer_records WHERE transfer_id='x'")[0] == 'running'
    assert KeychainStore(reopened, key_file_path=tmp_path / 'keychains.key').get_item(key['cred_id'])['secret_value'] == 'test-only'
    assert history_class(reopened).get_entry('machine', 'active')['status'] == 'interrupted'
    assert TransferHistoryStore(reopened).get('x')['state'] == 'interrupted'
    reopened.close_thread_connection()


def test_reopen_accepts_equivalent_activity_column_order_and_preserves_history(db, history_class):
    store = history_class(db)
    create_activity(store, connection(), 'retained', 'retained activity', status='success')
    # A physical schema can have the same named fields in a different order.
    # Move client_id to the end, changing the cids of subsequent indexed fields.
    sql = db.fetch_one("SELECT sql FROM sqlite_master WHERE name='activity_records'")[0]
    index_sql = [r[0] for r in db.fetch_all(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='activity_records' AND sql IS NOT NULL")]
    column = "client_id TEXT NOT NULL DEFAULT ''"
    sql = sql.replace(column + ',', '').rstrip().removesuffix(')') + ', ' + column + ')'
    with db.transaction() as conn:
        conn.execute('ALTER TABLE activity_records RENAME TO activity_records_old')
        conn.execute(sql)
        columns = ', '.join(row[1] for row in conn.execute('PRAGMA table_info(activity_records)'))
        conn.execute(f'INSERT INTO activity_records ({columns}) SELECT {columns} FROM activity_records_old')
        conn.execute('DROP TABLE activity_records_old')
        for statement in index_sql:
            conn.execute(statement)
    db.close_thread_connection()
    reopened = RchDatabase(db.db_path)
    try:
        assert history_class(reopened).get_entry('machine', 'retained')['status'] == 'success'
        assert reopened.integrity_check() == 'ok'
        assert reopened.fetch_all('PRAGMA table_info(activity_records)')[-1][1] == 'client_id'
        create_activity(history_class(reopened), connection(), 'new', 'new activity', status='success')
        assert history_class(reopened).count_activities('machine') == 2
    finally:
        reopened.close_thread_connection()


@pytest.mark.parametrize('table,column', [('activity_records', 'summary'),
                                          ('keychain_entries', 'hostname'),
                                          ('transfer_records', 'filename')])
def test_extra_nonunique_index_does_not_block_startup(db, table, column):
    db.execute(f'CREATE INDEX custom_lookup ON {table}({column})')
    db.close_thread_connection()
    reopened = RchDatabase(db.db_path)
    try:
        assert reopened.fetch_one("SELECT name FROM sqlite_master WHERE name='custom_lookup'") is not None
    finally:
        reopened.close_thread_connection()


def test_incorrect_required_index_is_rejected_with_name(db):
    db.execute('DROP INDEX idx_activity_machine_time')
    db.execute('CREATE INDEX idx_activity_machine_time ON activity_records(machine_id)')
    db.close_thread_connection()
    with pytest.raises(RuntimeError, match='missing or changed indexes: idx_activity_machine_time'):
        RchDatabase(db.db_path)


def test_unexpected_unique_index_is_rejected(db):
    db.execute('CREATE UNIQUE INDEX custom_unique ON activity_records(summary)')
    db.close_thread_connection()
    with pytest.raises(RuntimeError, match='unexpected unique indexes: custom_unique'):
        RchDatabase(db.db_path)


def test_incompatible_domain_table_is_rejected_during_base_startup(db):
    db.execute('ALTER TABLE activity_records ADD COLUMN invalid_field TEXT')
    db.close_thread_connection()
    with pytest.raises(RuntimeError, match='incompatible schema for activity_records'):
        RchDatabase(db.db_path)


def test_nested_transaction_rollback_and_reuse_across_actual_stores(db):
    settings = SettingsStore(db, 'qa')
    paths = PinnedPathStore(db)
    commands = PinnedCommandStore(db, lambda: '2026-01-01')
    jobs = BackgroundJobStore(db)
    connections = ConnectionHistoryStore(db)
    with pytest.raises(ValueError, match='abort outer'):
        with db.transaction() as outer:
            settings.write({'enabled': True})
            paths.save_item('m', 'test', '/tmp/test')
            commands.set_command_pinned('m', 'pwd', True)
            jobs.apply_status_report({'job_id': 'job', 'machine_id': 'm', 'client_id': 'c', 'state': 'running'})
            connections.record_connected({'machine_id': 'm', 'client_id': 'c'})
            with db.transaction() as inner:
                assert outer is inner is db.connection()
                assert len(paths.list_items('m')) == 1
            raise ValueError('abort outer')
    assert settings.read() == {}
    assert paths.list_items('m') == []
    assert commands.get_items('m') == []
    assert jobs.list_raw_jobs(machine_id='m') == []
    assert connections.get_identity_by_client_id('c') == ('', '', '')
    with db.transaction():
        settings.write({'outer': 1})
        paths.save_item('m', 'test', '/tmp/test')
        commands.set_command_pinned('m', 'pwd', True)
        with pytest.raises(RuntimeError, match='abort inner'):
            with db.transaction():
                settings.write({'inner': 1})
                paths.save_item('m', 'discard', '/tmp/discard')
                raise RuntimeError('abort inner')
        assert settings.read() == {'outer': 1}
    assert settings.read() == {'outer': 1}
    assert [p['display_name'] for p in paths.list_items('m')] == ['test']
    assert commands.get_items('m')[0]['command'] == 'pwd'
    assert not db.connection().in_transaction


def test_commit_failure_and_base_exception_leave_connection_reusable(db):
    db.execute('CREATE TABLE test_parent(id INTEGER PRIMARY KEY)')
    db.execute('CREATE TABLE test_child(id INTEGER REFERENCES test_parent(id) DEFERRABLE INITIALLY DEFERRED)')
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute('INSERT INTO test_child VALUES (42)')
    assert not db.connection().in_transaction
    assert db.fetch_all('SELECT * FROM test_child') == []
    with pytest.raises(KeyboardInterrupt):
        with db.transaction():
            db.execute('INSERT INTO test_parent VALUES (42)')
            raise KeyboardInterrupt
    assert db.fetch_all('SELECT * FROM test_parent') == []
    with db.transaction():
        db.execute('INSERT INTO test_parent VALUES (42)')
        db.execute('INSERT INTO test_child VALUES (42)')
    assert db.fetch_one('SELECT id FROM test_child')[0] == 42


def test_read_snapshot_is_consistent_and_does_not_block_wal_writer(db):
    settings = SettingsStore(db, 'snapshot')
    settings.write({'value': 1})
    main_conn = db.connection()
    errors, other_connections = [], []
    def worker():
        try:
            other_connections.append(db.connection())
            settings.write({'value': 2})
        except Exception as exc:
            errors.append(exc)
        finally:
            db.close_thread_connection()
    with db.read_snapshot() as current:
        assert current is main_conn
        assert settings.read() == {'value': 1}
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(3)
        assert not thread.is_alive()
        assert not errors and other_connections[0] is not main_conn
        with db.read_snapshot() as nested:
            assert nested is main_conn and settings.read() == {'value': 1}
        with pytest.raises(RuntimeError, match='read snapshot'):
            with db.transaction():
                pass
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            settings.write({'value': 3})
    assert settings.read() == {'value': 2}
    with db.transaction():
        settings.write({'value': 4})
        with db.read_snapshot():
            assert settings.read() == {'value': 4}
    assert settings.read() == {'value': 4}


def test_composed_write_does_not_invert_store_lock_order(db, monkeypatch):
    paths = PinnedPathStore(db)
    attempted = threading.Event()
    errors = []
    main_thread = threading.get_ident()
    transaction = db.transaction

    @contextmanager
    def observe_transaction():
        if threading.get_ident() != main_thread:
            attempted.set()
        with transaction() as conn:
            yield conn

    monkeypatch.setattr(db, 'transaction', observe_transaction)
    def worker():
        try:
            paths.save_item('m', 'worker', '/tmp/worker')
        except Exception as exc:
            errors.append(exc)
        finally:
            db.close_thread_connection()

    with db.transaction():
        thread = threading.Thread(target=worker)
        thread.start()
        assert attempted.wait(2)
        paths.save_item('m', 'outer', '/tmp/outer')
    thread.join(3)
    assert not thread.is_alive() and not errors
    assert {p['display_name'] for p in paths.list_items('m')} == {'outer', 'worker'}


def test_history_page_filter_count_delete_and_quick_pins_remain_independent(db, history_class):
    store = history_class(db)
    c = connection()
    create_activity(store, c, 'a', 'find item', status='error')
    create_activity(store, c, 'b', 'find item', status='success')
    create_activity(store, c, 'c', 'other', status='error')
    create_activity(store, connection('other-machine'), 'd', 'find item', status='error')
    page = store.view_service.get_execution_history_page('machine', query='find', limit=1)
    assert page['total_count'] == 2 and page['has_more']
    next_page = store.view_service.get_execution_history_page('machine', query='find', limit=1, cursor=page['next_cursor'])
    assert {page['items'][0]['activity_id'], next_page['items'][0]['activity_id']} == {'a', 'b'}
    assert store.view_service.get_connection_command_counts_by_machine_id('machine', ['client']) == {'client': 3}
    assert store.view_service.get_connection_command_totals('machine') == {'total': 3, 'unassigned': 0}
    for i in range(2):
        store.quick_store.begin(str(i), c, 'find item')
        store.quick_store.finish(str(i), 'success')
    store.set_command_pinned_by_machine_id('machine', 'find item', True)
    store.set_command_pinned_by_machine_id('machine', 'other', True)
    assert store.move_pinned_command_by_machine_id('machine', 'other', 'up')
    assert store.get_history_by_machine_id('machine')[1]['use_count'] == 2
    assert store.write_service.clear_execution_history_by_machine_id('machine', query='find', errors=True) == 1
    assert store.get_entry('machine', 'a') is None and store.get_entry('machine', 'b') is not None
    store.write_service.clear_history_by_machine_id('machine', query='FIND')
    assert [p['command'] for p in store.get_history_by_machine_id('machine')] == ['other', 'find item']
    assert store.count_activities('machine') == 2
    assert store.count_activities('other-machine') == 1


def test_concurrent_history_result_appends_and_terminal_updates(db, history_class):
    store = history_class(db)
    c = connection()
    create_activity(store, c, 'entry', 'result')
    errors = []
    def append(start):
        try:
            for i in range(start, start + 12):
                store.write_service.append_client_result(c, 'entry', {
                    'type': 'result', 'id': 1, 'event_type': 'chunk', 'message': str(i)})
        except Exception as exc:
            errors.append(exc)
        finally:
            db.close_thread_connection()
    threads = [threading.Thread(target=append, args=(i,)) for i in (0, 12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert not errors
    store.update_entry_status_for_connection(c, 'entry', 'success')
    store.update_entry_status_for_connection(c, 'entry', 'error')
    store.write_service.append_client_result(c, 'entry', {
        'type': 'result', 'id': 1, 'event_type': 'chunk', 'message': 'ignored'})
    item = store.get_entry('machine', 'entry')
    assert item['status'] == 'success'
    assert {x['message'] for x in item['result']} == {str(i) for i in range(24)}
    assert len(item['result']) == len(item['recorded_at']) == 24
    assert db.fetch_one("SELECT result_message_bytes FROM activity_records WHERE activity_id='entry'")[0] == sum(len(str(i)) for i in range(24))


def test_background_job_identity_precedence_and_reporting(db):
    recent = RecentDeviceStore(db)
    connections = ConnectionHistoryStore(db)
    jobs = BackgroundJobStore(db)
    events = Mock()
    live = {'online': SimpleNamespace(session_info=SimpleNamespace(machine_id='live', hostname='live-host', addr='live-addr'))}
    service = BackgroundJobService(events, jobs, None, None,
        server=SimpleNamespace(get_target_connection_by_client_id=live.get),
        recent_device_store=recent, connection_history_store=connections)
    recent.upsert_from_connection({'machine_id': 'recent', 'client_id': 'online', 'hostname': 'recent-host', 'addr': 'recent-addr'})
    connections.record_connected({'machine_id': 'old', 'client_id': 'online', 'hostname': 'old-host', 'addr': 'old-addr'})
    assert service._resolve_client_context('online') == ('live', 'live-host', 'live-addr')
    live.clear()
    assert service._resolve_client_context('online') == ('recent', 'recent-host', 'recent-addr')
    connections.record_connected({'machine_id': 'historic', 'client_id': 'historical', 'hostname': 'old-host', 'addr': 'old-addr'})
    assert service._resolve_client_context('historical') == ('historic', 'old-host', 'old-addr')
    jobs.apply_status_report({'job_id': 'previous', 'machine_id': 'fallback', 'client_id': 'orphan', 'hostname': 'fallback-host', 'addr': 'fallback-addr', 'state': 'stopped'})
    assert service._resolve_client_context('orphan') == ('fallback', 'fallback-host', 'fallback-addr')
    assert service._resolve_client_context('unknown') == ('', '', '')
    payload = {'job_id': 'new', 'client_id': 'historical', 'job_name': 'test', 'job_key': 'test'}
    assert service.ingest_report({**payload, 'event_type': 'status', 'state': 'running'})['machine_id'] == 'historic'
    service.ingest_report({**payload, 'event_type': 'message', 'text': 'hello'})
    service.ingest_report({**payload, 'event_type': 'status', 'state': 'stopped'})
    job = service.get_job('historical', 'new')
    assert job['messages'][0]['text'] == 'hello' and job['state'] == 'stopped'
    assert service.list_jobs('historical')[0]['message_count'] == 1
    service.delete_job_record('historical', 'new')
    assert jobs.get_raw_job('new') is None
    assert db.fetch_one("SELECT COUNT(*) FROM background_job_messages WHERE job_id='new'")[0] == 0


def test_no_domain_ddl_or_private_history_store_access():
    backend = Path(__file__).resolve().parents[1]
    for path in (backend / 'server/application').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.lstrip().upper().startswith(('CREATE TABLE ', 'CREATE INDEX ', 'CREATE UNIQUE INDEX ')), path
    for path in ('history/history_view_service.py', 'history/history_write_service.py',
                 'jobs/background_job_service.py'):
        source = (backend / 'server/application' / path).read_text()
        assert '.database.' not in source and '.store._' not in source
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.lstrip().upper().startswith(('SELECT ', 'INSERT INTO ', 'UPDATE ', 'DELETE FROM ')), path
