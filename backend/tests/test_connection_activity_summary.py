"""Session history is a lightweight Activity read model, not a command-detail view."""
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types


def load_view_service(monkeypatch):
    # Isolate HistoryViewService's page logic without requiring web-server auth
    # dependencies (the normal application imports the real config module).
    config = types.ModuleType('server.config.config')
    config.COMMAND_HISTORY_PAGE_SIZE = 50
    config.COMMAND_HISTORY_MAX_PAGE_SIZE = 200
    monkeypatch.setitem(sys.modules, 'server.config.config', config)
    module_file = Path(__file__).resolve().parents[1] / 'server/application/history/history_view_service.py'
    spec = importlib.util.spec_from_file_location('connection_activity_summary_test_module', module_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HistoryViewService


class Store:
    def __init__(self, entries):
        self.entries = entries
        self._lock = threading.RLock()
        self.artifact_service = None

    @staticmethod
    def _row_to_entry(row):
        return {key: (json.loads(value) if key == 'invocation' else value)
                for key, value in row.items() if key != 'started_at_ms'}

    def _list_execution_rows(self, machine_id, *, limit=None, cursor=None, client_id='', **filters):
        rows = sorted((r for r in self.entries if r['machine_id'] == machine_id and
                       (not client_id or r['client_id'] == client_id)),
                      key=lambda r: (r['started_at_ms'], r['activity_id']), reverse=True)
        if cursor:
            rows = [r for r in rows if (r['started_at_ms'], r['activity_id']) < cursor]
        return rows[:limit]

    def count_activities(self, machine_id, *, client_id='', **filters):
        return sum(r['machine_id'] == machine_id and (not client_id or r['client_id'] == client_id)
                   for r in self.entries)


def record(i, kind, action, invocation, *, machine='m1', client='c1'):
    return dict(activity_id=str(i), machine_id=machine, client_id=client, kind=kind,
                action=action, invocation=json.dumps(invocation), status='success',
                created_at='2026-10-21T00:00:00+00:00', started_at='2026-10-21T00:00:00+00:00',
                finished_at='2026-10-21T00:00:01+00:00', started_at_ms=i)


def test_connection_history_summarizes_all_activity_kinds_without_internal_payload(monkeypatch):
    View = load_view_service(monkeypatch)
    records = [
        record(1, 'command', 'invoke', {'input': 'shell pwd'}),
        record(2, 'remote_files', 'rename_files', {'arguments': {'old_path': '/home/a', 'new_name': 'b'}}),
        record(3, 'transfer', 'upload_files', {'arguments': {'filename': 'test.txt'}}),
        record(4, 'external_tool', 'run_exec', {'input': 'xt ffmpeg -- -version', 'arguments': {'exec_name': 'ffmpeg', 'token': 'PRIVATE'}}),
        record(5, 'script', 'invoke', {'input': 'script exec foo'}),
        record(6, 'alias', 'invoke', {'input': 'my-alias'}),
        record(7, 'remote_files', 'delete_files', {'arguments': {'paths': ['/one', '/two']}}),
    ]
    records.append(record(8, 'command', 'invoke', {'input': 'other'}, client='c2'))
    records.append(record(9, 'command', 'invoke', {'input': 'other'}, machine='m2'))
    view = View(Store(records))
    view._resolve_artifact = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Must not resolve Artifacts'))
    first = view.get_connection_command_page('m1', 'c1', limit=3)
    assert first['total_count'] == 7 and first['has_more']
    assert [x['summary'] for x in first['items']] == ['Delete files', 'my-alias', 'Script']
    assert all(set(x) == {'activity_id', 'kind', 'action', 'summary', 'status', 'created_at', 'started_at', 'finished_at'} for x in first['items'])
    second = view.get_connection_command_page('m1', 'c1', limit=4, cursor=first['next_cursor'])
    assert [x['summary'] for x in second['items']] == ['Run ffmpeg', 'Upload files', 'Rename', 'shell pwd']
    assert not second['has_more'] and len(second['items']) == 4
    assert 'PRIVATE' not in str(first) + str(second)
    assert '__json__' not in str(first) + str(second)


def test_connection_projection_handles_empty_and_rejects_missing_client(monkeypatch):
    View = load_view_service(monkeypatch)
    view = View(Store([]))
    assert view.get_connection_command_page('m1', 'c1')['items'] == []
    try:
        view.get_connection_command_page('m1', '')
    except ValueError as exc:
        assert 'client' in str(exc)
    else:
        raise AssertionError('Expected invalid client ID')
