"""Task output recovery reads the exact Activity, never another short command."""
from types import SimpleNamespace
import pytest

pytest.importorskip("werkzeug", reason="history integration requires configured Flask/Werkzeug environment")

from server.application.history.history_store import CommandHistoryStore
from server.application.web.command_history_api import WebCommandHistoryApi
from server.persistence.rch_database import RchDatabase


def test_exact_activity_lookup_returns_finished_output_and_rejects_wrong_machine(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    history = CommandHistoryStore(db)
    server = SimpleNamespace(command_history=history)
    api = WebCommandHistoryApi(server)
    conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m1', client_id='c1'))
    for activity_id, text in (('activity-first', 'alpha'), ('activity-second', 'beta')):
        history.write_service.create_activity_for_dispatch(conn, activity_id, {
            'kind': 'command', 'action': 'ls', 'origin': 'web', 'presentation': 'terminal',
            'invocation': {'input': 'ls'}, 'resolved': {},
        })
        history.write_service.append_output_for_connection(conn, activity_id, 0, text)
        history.write_service.update_entry_status_for_connection(conn, activity_id, 'success')
    entry = api.get_command_execution_history_entry('m1', 'activity-first')
    assert entry['client_id'] == 'c1'
    assert entry['finished_at']
    assert entry['result']['output_records'][0]['text'] == 'alpha'
    assert api.get_command_execution_history_entry('m1', 'activity-second')['result']['output_records'][0]['text'] == 'beta'
    try:
        api.get_command_execution_history_entry('m2', 'activity-first')
        assert False, 'other machine must not access this Activity'
    except ValueError as exc:
        assert str(exc) == 'Activity not found'
