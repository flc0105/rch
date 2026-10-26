"""Focused behavior tests for project module: history."""

import sqlite3
from contextlib import contextmanager
from threading import RLock
from types import SimpleNamespace
import pytest
from server.application.history.history_write_service import HistoryWriteService
from server.application.web.command_history_api import WebCommandHistoryApi


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE activity_records (machine_id TEXT, activity_id TEXT, kind TEXT, status TEXT, action TEXT, invocation_json TEXT, resolved_json TEXT)')

    def connection(self):
        return self.conn

    @contextmanager
    def transaction(self):
        with self.conn:
            yield self.conn


class Store:
    def __init__(self):
        self.database = Database()
        self._lock = RLock()
        self.quick_store = SimpleNamespace()

    def _activity_filters(self, machine_id, *, query='', kind='', errors=False):
        # Exercise SQL built by the real writer against this independently provided filter.
        clauses, params = ['machine_id = ?'], [machine_id]
        if kind:
            clauses.append('kind = ?')
            params.append(kind)
        if errors:
            clauses.append("status IN ('error','cancelled','interrupted','timed_out')")
        if query:
            clauses.append('(instr(LOWER(action), LOWER(?)) > 0 OR instr(LOWER(invocation_json), LOWER(?)) > 0 OR instr(LOWER(resolved_json), LOWER(?)) > 0)')
            params.extend([query]*3)
        return clauses, params


def test_scoped_activity_delete_clears_every_matching_row_and_never_quick():
    store=Store()
    entries=[('m1','a1','script','error','deploy','{}','{}'),('m1','a2','script','success','deploy','{}','{}'),
             ('m1','a3','script','error','build','{}','{}'),('m1','a4','command','error','deploy','{}','{}'),
             ('m2','a5','script','error','deploy','{}','{}')]
    store.database.conn.executemany('INSERT INTO activity_records VALUES (?,?,?,?,?,?,?)',entries)
    quick={'history': ['do not mutate'], 'pins': ['preserve']}
    store.quick_store = quick
    writer=HistoryWriteService(store)
    assert writer.clear_execution_history_by_machine_id('m1',kind='script',errors=True,query='deploy')==1
    assert store.database.conn.execute('SELECT activity_id FROM activity_records ORDER BY activity_id').fetchall()==[(x,) for x in ('a2','a3','a4','a5')]
    assert quick=={'history':['do not mutate'],'pins':['preserve']}
    assert writer.clear_execution_history_by_machine_id('m1')==3
    assert store.database.conn.execute('SELECT activity_id FROM activity_records').fetchall()==[('a5',)]


def test_api_validates_kind_before_deleting():
    store=Store()
    writer=HistoryWriteService(store)
    api=WebCommandHistoryApi(SimpleNamespace(command_history=SimpleNamespace(write_service=writer)))
    with pytest.raises(ValueError,match='Invalid activity kind'):
        api.clear_command_execution_history('m1', kind='bogus')
    assert api.clear_command_execution_history('m1',kind='script')['removed_count']==0


def test_quick_clear_search_deletes_only_matching_recent_commands_and_keeps_pins():
    # Load QuickHistoryStore with just its numeric config; the Web framework is not needed.
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from types import ModuleType
    from unittest.mock import patch
    import sys

    config = ModuleType('server.config.config')
    config.COMMAND_HISTORY_RECENT_LIMIT = 100
    path = Path(__file__).resolve().parents[2] / 'server/application/history/quick_history.py'
    spec = spec_from_file_location('_quick_history_scoped_clear_test', path)
    module = module_from_spec(spec)
    with patch.dict(sys.modules, {'server.config.config': config}):
        spec.loader.exec_module(module)
    QuickHistoryStore = module.QuickHistoryStore

    store = Store()
    store.database.conn.execute('''
        CREATE TABLE command_recents (
            machine_id TEXT, command TEXT, last_used_at TEXT,
            use_count INTEGER, snapshot_json TEXT
        )
    ''')
    store.database.conn.executemany(
        'INSERT INTO command_recents VALUES (?,?,?,?,?)', [
            ('m1', 'deploy staging', '', 1, '{}'),
            ('m1', 'Deploy production', '', 1, '{}'),
            ('m1', 'build package', '', 1, '{}'),
            ('m2', 'deploy remote', '', 1, '{}'),
            ('m1', 'ÄBC sample', '', 1, '{}'),
        ],
    )
    store.quick_store = QuickHistoryStore(store)
    pins = ['deploy staging']
    store.pinned_store = SimpleNamespace(items=pins)
    writer = HistoryWriteService(store)
    api = WebCommandHistoryApi(SimpleNamespace(command_history=SimpleNamespace(write_service=writer)))
    api.clear_command_history('m1', query='dEploy')
    remaining = store.database.conn.execute(
        'SELECT machine_id, command FROM command_recents ORDER BY machine_id, command').fetchall()
    assert remaining == [('m1', 'build package'), ('m1', 'ÄBC sample'), ('m2', 'deploy remote')]
    assert pins == ['deploy staging']
    # A search term must be treated as literal text, not an SQL wildcard.
    api.clear_command_history('m1', query='%')
    assert store.database.conn.execute('SELECT COUNT(*) FROM command_recents').fetchone()[0] == 3
    api.clear_command_history('m1', query='äbc')
    assert store.database.conn.execute('SELECT COUNT(*) FROM command_recents').fetchone()[0] == 2
    api.clear_command_history('m1')
    assert store.database.conn.execute('SELECT command FROM command_recents').fetchall() == [('deploy remote',)]
    assert pins == ['deploy staging']
