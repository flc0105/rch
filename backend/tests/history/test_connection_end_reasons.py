"""Connection end diagnosis stays independent of the original session state label."""
import errno
import os
import sqlite3
import socket
import tempfile
import time
from types import SimpleNamespace

import pytest

from client.connection.server_connection import ServerConnection
from core.protocol.message_types import MSG_TYPE_SESSION_END
from server.application.connection.connection_history_store import ConnectionHistoryStore
from server.application.connection.connection_service import WebConnectionService
from server.connection.context.session_context import ClientSessionContext
from server.connection.services.message_dispatcher import ServerInboundMessageDispatcher
from server.persistence.rch_database import RchDatabase
from server.runtime.server_listener import ServerListener


def _connection():
    return {
        'machine_id': 'machine-A', 'client_id': 'client-X',
        'connected_at': '2026-10-26T10:00:00',
        'disconnected_at': '2026-10-26T10:00:08',
    }


def _new_store(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(db)
    store.record_connected(_connection())
    return db, store


def test_connection_history_new_fields_preserve_existing_state_and_detail(tmp_path):
    db, store = _new_store(tmp_path)
    store.record_disconnected(_connection(), termination_reason='client_error', diagnostics={
        'summary': 'RuntimeError: crash', 'traceback': 'Traceback (most recent call last): ...',
    })
    item = store.get_history('machine-A')['sessions'][0]
    assert item['termination_reason'] == 'client_error'
    assert item['error_diagnostics']['summary'] == 'RuntimeError: crash'
    assert 'Traceback' in item['error_diagnostics']['traceback']
    assert item['connection_state'] == 'offline'
    assert item['disconnect_reason'] == 'disconnected'
    # Later close callbacks must not replace the first conclusive diagnosis.
    store.record_disconnected(_connection(), termination_reason='transport_error', diagnostics={'summary': 'later'})
    assert store.get_history('machine-A')['sessions'][0]['termination_reason'] == 'client_error'
    db.close_thread_connection()


def test_connection_history_schema_uses_explicit_termination_columns(tmp_path):
    db, store = _new_store(tmp_path)
    columns = {entry['name'] for entry in db.connection().execute('PRAGMA table_info(connection_sessions)')}
    assert {'termination_reason', 'error_diagnostics_json', 'disconnect_reason'} <= columns
    assert 'reason' not in columns
    assert 'detail_json' not in columns
    store.record_disconnected(_connection(), termination_reason='transport_error', diagnostics={
        'summary': 'Connection reset', 'traceback': 'Traceback (most recent call last): ...',
    })
    row = db.connection().execute("SELECT termination_reason, error_diagnostics_json, disconnect_reason FROM connection_sessions").fetchone()
    assert row['termination_reason'] == 'transport_error'
    assert row['disconnect_reason'] == 'disconnected'
    assert 'Connection reset' in row['error_diagnostics_json']
    assert store.get_history('machine-A')['sessions'][0]['error_diagnostics']['summary'] == 'Connection reset'
    db.close_thread_connection()


def test_unrecognized_connection_history_columns_stop_without_rewriting(tmp_path):
    db, _ = _new_store(tmp_path)
    db.close_thread_connection()
    database_path = str(tmp_path / 'rch.db')
    with sqlite3.connect(database_path) as connection:
        connection.execute('ALTER TABLE connection_sessions RENAME COLUMN termination_reason TO reason')
    with pytest.raises(RuntimeError, match='incompatible schema'):
        RchDatabase(database_path)
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(connection_sessions)')}
    assert 'reason' in columns
    assert 'termination_reason' not in columns
    assert 'error_diagnostics_json' in columns

def test_interrupted_tag_stays_unchanged_when_server_recovers(tmp_path):
    db, store = _new_store(tmp_path)
    store.reconcile_active_sessions('machine-A', set())
    item = store.get_history('machine-A')['sessions'][0]
    assert item['connection_state'] == 'interrupted'
    assert item['disconnect_reason'] == 'server_interrupted'
    assert item['termination_reason'] == ''
    assert item['error_diagnostics'] == {}
    db.close_thread_connection()


def test_client_end_message_is_validated_bounded_and_captured():
    context = ClientSessionContext()
    session = SimpleNamespace(context=context)
    dispatcher = ServerInboundMessageDispatcher(session)
    dispatcher.dispatch({'type': MSG_TYPE_SESSION_END, 'reason': 'client_error', 'detail': {
        'summary': 'a' * 900, 'traceback': 'b' * 20000,
    }})
    assert context.client_session_end['reason'] == 'client_error'
    assert len(context.client_session_end['detail']['summary']) == 500
    assert len(context.client_session_end['detail']['traceback']) == 12000
    dispatcher.dispatch({'type': MSG_TYPE_SESSION_END, 'reason': 'server_requested_disconnect'})
    assert context.client_session_end['reason'] == 'client_error'


def test_client_reports_reason_before_shutdown():
    client = ServerConnection()
    try:
        captured = []
        client.send = captured.append
        client.report_session_end('client_restart')
        assert captured == [{
            'type': MSG_TYPE_SESSION_END, 'reason': 'client_restart',
        }]
    finally:
        client.close()


def _complete_session(store, *, request=None, client_end=None, failure=None):
    ctx = ClientSessionContext()
    ctx.server_disconnect_request = request
    ctx.client_session_end = client_end
    ctx.transport_failure = failure
    session = SimpleNamespace(
        context=ctx,
        session_info=SimpleNamespace(client_id='client-X'),
        services=SimpleNamespace(heartbeat_service=SimpleNamespace(mark_disconnected=lambda: None)),
    )
    service = WebConnectionService(
        server=SimpleNamespace(), event_bus=SimpleNamespace(), artifact_service=None,
        connection_history_store=store,
    )
    service.serialize_connection = lambda _: _connection()
    service.publish_connection_offline = lambda _: None
    service.handle_connection_closed(session)
    return store.get_history('machine-A')['sessions'][0]


def test_server_requested_reason_groups_server_and_client_reports(tmp_path):
    _, store = _new_store(tmp_path)
    item = _complete_session(store,
        request={'at': time.monotonic()},
        client_end={'reason': 'client_exit', 'detail': {'summary': 'Exited'}},
        failure={'reason': 'connection_lost', 'detail': {'summary': 'EOF'}},
    )
    assert item['termination_reason'] == 'server_requested_disconnect'
    assert item['error_diagnostics'] == {}
    assert item['disconnect_reason'] == 'disconnected'


def test_client_restart_and_update_take_precedence_over_socket_eof(tmp_path):
    for reason in ('client_exit', 'client_restart', 'client_update', 'client_error'):
        with tempfile.TemporaryDirectory() as directory:
            db = RchDatabase(os.path.join(directory, 'rch.db'))
            store = ConnectionHistoryStore(db)
            store.record_connected(_connection())
            item = _complete_session(store,
                client_end={'reason': reason, 'detail': {'summary': 'Observed client shutdown'}},
                failure={'reason': 'connection_lost', 'detail': {'summary': 'Socket EOF'}},
            )
            assert item['termination_reason'] == reason
            db.close_thread_connection()


def test_receive_error_classification(tmp_path):
    class FakeServer:
        def __init__(self):
            self.recorded = []
            self.connections = SimpleNamespace(remove=lambda session: None)
            self.web_service = SimpleNamespace(connection_api=SimpleNamespace(
                handle_connection_closed=lambda session: self.recorded.append(session.context.transport_failure),
            ))

    server = FakeServer()
    listener = ServerListener(server)
    for exc, expected in (
        (OSError('Connection closed'), 'connection_lost'),
        (OSError('Connection aborted'), 'unexpected_disconnect'),
        (OSError(errno.ECONNRESET, 'reset'), 'transport_error'),
        (socket.timeout('idle timeout'), 'timeout'),
    ):
        context = ClientSessionContext()
        session = SimpleNamespace(context=context, session_info=SimpleNamespace(client_id='client-X'),
                                  address='127.0.0.1:1234',
                                  runtime=SimpleNamespace(message_queue=SimpleNamespace(put=lambda *args: None)))
        listener._handle_connection_closed(session, exc)
        assert context.transport_failure['reason'] == expected
        if expected == 'connection_lost':
            assert context.transport_failure['detail'] == {}
        else:
            assert context.transport_failure['detail']['summary']


def test_server_command_marks_disconnect_only_after_dispatch_succeeds():
    from server.connection.channel.session_command_channel import ClientSessionCommandChannel

    sent = []
    noted = []

    class Queue:
        def put(self, value):
            pass

        def peek_first(self):
            return None

    session = SimpleNamespace(
        context=SimpleNamespace(command_history_orchestrator=None),
        runtime=SimpleNamespace(bind_command_execution=lambda *a, **k: None,
                                pending_command_ids=Queue(),
                                wait_for_result=lambda *a, **k: iter(())),
        send=sent.append, note_server_disconnect=lambda: noted.append(None),
    )
    channel = ClientSessionCommandChannel(session)
    channel.send_command('kill_instance')
    channel.send_command('kill_connection')
    channel.send_command('help')
    assert noted == [None, None]
    assert [row['text'] for row in sent] == ['kill_instance', 'kill_connection', 'help']


def test_expired_server_intent_uses_actual_client_report(tmp_path):
    _, store = _new_store(tmp_path)
    item = _complete_session(
        store,
        request={'at': time.monotonic() - 121},
        client_end={'at': time.monotonic(), 'reason': 'client_restart',
                    'detail': {'summary': 'Client restarted'}},
    )
    assert item['termination_reason'] == 'client_restart'
    assert item['error_diagnostics'] == {}


def test_new_session_reuses_client_identity_and_resets_diagnosis(tmp_path):
    _, store = _new_store(tmp_path)
    store.record_disconnected(_connection(), termination_reason='timeout', diagnostics={'summary': 'timeout'})
    store.record_connected(_connection())
    item = store.get_history('machine-A')['sessions'][0]
    assert item['termination_reason'] == ''
    assert item['error_diagnostics'] == {}
    assert item['connection_state'] == 'online'


def test_normal_termination_displays_only_cause(tmp_path):
    for cause in ('server_requested_disconnect', 'client_exit', 'client_restart', 'client_update', 'connection_lost'):
        with tempfile.TemporaryDirectory() as directory:
            db = RchDatabase(os.path.join(directory, 'rch.db'))
            store = ConnectionHistoryStore(db)
            store.record_connected(_connection())
            store.record_disconnected(_connection(), termination_reason=cause,
                                      diagnostics={'summary': 'A generic repeated message'})
            item = store.get_history('machine-A')['sessions'][0]
            assert item['termination_reason'] == cause
            assert item['error_diagnostics'] == {}
            db.close_thread_connection()


def test_http_control_tracks_only_actions_delivered_to_watchdog(monkeypatch, tmp_path):
    from server.application.connection.control_command_store import ControlCommandStore
    import server.application.connection.connection_service as connection_service

    control = ControlCommandStore()
    monkeypatch.setattr(connection_service, 'get_control_command_store', lambda: control)
    _, store = _new_store(tmp_path)

    control.set_pending_command('client-X', 'kill')
    assert control.take_delivered_shutdown('client-X') == ''
    assert control.pop_pending_command('client-X')['command'] == 'kill'
    assert control.pop_pending_command('client-X') is None
    assert control.take_delivered_shutdown('client-X') == 'kill'
    assert control.take_delivered_shutdown('client-X') == ''

    control.set_pending_command('client-X', 'kill')
    control.pop_pending_command('client-X')
    item = _complete_session(store, failure={'reason': 'connection_lost', 'detail': {}})
    assert item['termination_reason'] == 'server_requested_disconnect'
    assert item['error_diagnostics'] == {}
    assert control.take_delivered_shutdown('client-X') == ''


def test_http_control_relaunch_and_clone_are_distinct(monkeypatch, tmp_path):
    from server.application.connection.control_command_store import ControlCommandStore
    import server.application.connection.connection_service as connection_service

    control = ControlCommandStore()
    monkeypatch.setattr(connection_service, 'get_control_command_store', lambda: control)
    control.set_pending_command('client-X', 'relaunch')
    control.pop_pending_command('client-X')
    _, store = _new_store(tmp_path)
    item = _complete_session(store, failure={'reason': 'connection_lost', 'detail': {}})
    assert item['termination_reason'] == 'client_restart'
    assert item['error_diagnostics'] == {}

    control.set_pending_command('client-Y', 'clone')
    control.pop_pending_command('client-Y')
    assert control.take_delivered_shutdown('client-Y') == ''


def test_http_control_expired_delivery_is_ignored(monkeypatch):
    from server.application.connection.control_command_store import ControlCommandStore
    control = ControlCommandStore()
    control.set_pending_command('client-X', 'kill')
    control.pop_pending_command('client-X')
    assert control.take_delivered_shutdown('client-X', max_age=-1) == ''
    assert control.take_delivered_shutdown('client-X') == ''
