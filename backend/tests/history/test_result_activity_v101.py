"""Activity keeps visible outputs separate from the temporary raw Result viewer."""
from contextlib import nullcontext
from threading import RLock
from types import SimpleNamespace

from server.application.history.history_write_service import HistoryWriteService


class Store:
    MAX_OUTPUT_RECORDS = 100
    MAX_OUTPUT_RECORD_CHARS = 10000

    def __init__(self):
        self._lock = RLock()
        self.database = SimpleNamespace(transaction=nullcontext)
        self.entry = {'status': 'running', 'result': {'output_records': [], 'result_events': []}}

    def _get_machine_id_from_conn(self, conn):
        return 'machine'

    def _get_entry(self, machine_id, entry_id):
        assert machine_id == 'machine' and entry_id == 'activity'
        return self.entry

    def _now_iso(self):
        return '2026-11-14T12:00:00'

    def _safe_text(self, value):
        return str(value)

    def _update_entry(self, entry):
        assert entry is self.entry


def test_raw_result_events_and_visible_output_stay_isolated():
    store = Store()
    svc = HistoryWriteService(store)
    conn = object()
    for event in [
        {'type': 'result', 'id': 99, 'event_type': 'progress', 'message': 'Loading'},
        {'type': 'result', 'id': 99, 'event_type': 'chunk', 'data': {'a': 1}},
        {'type': 'result', 'id': 99, 'event_type': 'completed', 'status': 'success', 'data': {'done': True}},
    ]:
        svc.append_result_event_for_connection(conn, 'activity', event)
    svc.append_output_for_connection(conn, 'activity', 1, 'Loading')
    svc.append_output_for_connection(conn, 'activity', 1, '{"a":1}')
    result = store.entry['result']
    assert [row['text'] for row in result['output_records']] == ['Loading', '{"a":1}']
    assert all('envelope' not in row for row in result['output_records'])
    assert [e['event_type'] for e in result['result_events']] == ['progress','chunk','completed']
    assert result['result_events'][-1]['id'] == 99
    assert result['result_events'][-1]['data'] == {'done': True}


def test_raw_result_inspection_has_bounded_storage():
    store=Store()
    store.MAX_OUTPUT_RECORDS=2
    svc=HistoryWriteService(store)
    for i in range(3):
        svc.append_result_event_for_connection(object(), 'activity', {
            'type':'result','id':i,'event_type':'chunk','message':'text'})
    assert len(store.entry['result']['result_events']) == 2
    assert store.entry['result']['result_events_truncated'] is True
