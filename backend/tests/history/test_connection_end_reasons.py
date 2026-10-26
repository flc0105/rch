"""Connection end state, cause and details follow the observed close event."""
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
    store.record_disconnected(_connection(), termination_reason='client_error', details={
        'summary': 'RuntimeError: crash', 'traceback': 'Traceback (most recent call last): ...',
    })
    item = store.get_history('machine-A')['sessions'][0]
    assert item['termination_reason'] == 'client_error'
    assert item['termination_detail']['summary'] == 'RuntimeError: crash'
    assert 'Traceback' in item['termination_detail']['traceback']
    assert item['connection_state'] == 'interrupted'
    assert item['disconnect_reason'] == 'interrupted'
    # Later close callbacks must not replace the first conclusive diagnosis.
    store.record_disconnected(_connection(), termination_reason='transport_error', details={'summary': 'later'})
    assert store.get_history('machine-A')['sessions'][0]['termination_reason'] == 'client_error'
    db.close_thread_connection()


def test_connection_history_schema_uses_explicit_termination_columns(tmp_path):
    db, store = _new_store(tmp_path)
    columns = {entry['name'] for entry in db.connection().execute('PRAGMA table_info(connection_sessions)')}
    assert {'termination_reason', 'termination_detail_json', 'disconnect_reason'} <= columns
    assert 'reason' not in columns
    assert 'detail_json' not in columns
    assert 'error_diagnostics_json' not in columns
    store.record_disconnected(_connection(), termination_reason='transport_error', details={
        'summary': 'Connection reset', 'traceback': 'Traceback (most recent call last): ...',
    })
    row = db.connection().execute("SELECT termination_reason, termination_detail_json, disconnect_reason FROM connection_sessions").fetchone()
    assert row['termination_reason'] == 'transport_error'
    assert row['disconnect_reason'] == 'interrupted'
    assert 'Connection reset' in row['termination_detail_json']
    assert store.get_history('machine-A')['sessions'][0]['termination_detail']['summary'] == 'Connection reset'
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
    assert 'termination_detail_json' in columns

def test_interrupted_tag_stays_unchanged_when_server_recovers(tmp_path):
    db, store = _new_store(tmp_path)
    store.reconcile_active_sessions('machine-A', set())
    item = store.get_history('machine-A')['sessions'][0]
    assert item['connection_state'] == 'interrupted'
    assert item['disconnect_reason'] == 'server_interrupted'
    assert item['termination_reason'] == ''
    assert item['termination_detail'] == {}
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
    service.publish_connection_offline = lambda *args, **kwargs: None
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
    assert item['termination_detail'] == {}
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


def test_kill_instance_client_report_is_server_requested_disconnect(tmp_path):
    db, store = _new_store(tmp_path)
    item = _complete_session(
        store,
        client_end={
            'at': time.monotonic(),
            'reason': 'client_exit',
            'detail': {'command': 'kill_instance'},
        },
        failure={'reason': 'connection_lost', 'detail': {}},
    )
    assert item['termination_reason'] == 'server_requested_disconnect'
    assert item['termination_detail'] == {'command': 'kill_instance'}
    assert item['connection_state'] == 'offline'
    db.close_thread_connection()


def test_connection_offline_event_contains_termination_reason(tmp_path):
    db, store = _new_store(tmp_path)
    published = []
    ctx = ClientSessionContext()
    ctx.transport_failure = {'reason': 'connection_lost', 'detail': {}}
    session = SimpleNamespace(
        context=ctx,
        session_info=SimpleNamespace(client_id='client-X'),
        services=SimpleNamespace(heartbeat_service=SimpleNamespace(mark_disconnected=lambda: None)),
    )
    service = WebConnectionService(
        server=SimpleNamespace(),
        event_bus=SimpleNamespace(publish=lambda event, payload: published.append((event, payload))),
        artifact_service=None,
        connection_history_store=store,
    )
    service.serialize_connection = lambda _: _connection()
    service.handle_connection_closed(session)
    offline_events = [payload for event, payload in published if event == 'connection_offline']
    assert len(offline_events) == 1
    assert offline_events[0]['termination_reason'] == 'connection_lost'
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


def test_generic_command_channel_does_not_infer_disconnect_intent():
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
        send=sent.append, note_server_disconnect=noted.append,
    )
    channel = ClientSessionCommandChannel(session)
    channel.send_command('kill_instance')
    channel.send_command('help')
    assert noted == []
    assert [row['text'] for row in sent] == ['kill_instance', 'help']


def test_expired_server_intent_uses_actual_client_report(tmp_path):
    _, store = _new_store(tmp_path)
    item = _complete_session(
        store,
        request={'at': time.monotonic() - 121},
        client_end={'at': time.monotonic(), 'reason': 'client_restart',
                    'detail': {'summary': 'Client restarted'}},
    )
    assert item['termination_reason'] == 'client_restart'
    assert item['termination_detail'] == {}


def test_new_session_reuses_client_identity_and_resets_diagnosis(tmp_path):
    _, store = _new_store(tmp_path)
    store.record_disconnected(_connection(), termination_reason='timeout', details={'summary': 'timeout'})
    store.record_connected(_connection())
    item = store.get_history('machine-A')['sessions'][0]
    assert item['termination_reason'] == ''
    assert item['termination_detail'] == {}
    assert item['connection_state'] == 'online'


def test_voluntary_shutdown_has_offline_tag_and_optional_command(tmp_path):
    for cause in ('server_requested_disconnect', 'client_exit', 'client_restart', 'client_update'):
        with tempfile.TemporaryDirectory() as directory:
            db = RchDatabase(os.path.join(directory, 'rch.db'))
            store = ConnectionHistoryStore(db)
            store.record_connected(_connection())
            store.record_disconnected(_connection(), termination_reason=cause,
                                      details={'command': 'kill_instance'})
            item = store.get_history('machine-A')['sessions'][0]
            assert item['termination_reason'] == cause
            assert item['connection_state'] == 'offline'
            assert item['disconnect_reason'] == 'disconnected'
            assert item['termination_detail'] == {'command': 'kill_instance'}
            db.close_thread_connection()


def test_abnormal_shutdown_has_interrupted_tag_and_actual_diagnostics(tmp_path):
    for cause in ('connection_lost', 'transport_error', 'timeout', 'unexpected_disconnect', 'client_error'):
        with tempfile.TemporaryDirectory() as directory:
            db = RchDatabase(os.path.join(directory, 'rch.db'))
            store = ConnectionHistoryStore(db)
            store.record_connected(_connection())
            details = {'summary': 'Connection reset', 'traceback': 'actual stack'} if cause != 'connection_lost' else {}
            store.record_disconnected(_connection(), termination_reason=cause, details=details)
            item = store.get_history('machine-A')['sessions'][0]
            assert item['termination_reason'] == cause
            assert item['connection_state'] == 'interrupted'
            assert item['disconnect_reason'] == 'interrupted'
            assert item['termination_detail'] == details
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
    assert item['termination_detail'] == {'command': 'httpctl kill'}
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
    assert item['termination_detail'] == {'command': 'httpctl relaunch'}

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


def test_protocol_and_storage_preserve_command_metadata(tmp_path):
    ctx = ClientSessionContext()
    session = SimpleNamespace(context=ctx)
    dispatcher = ServerInboundMessageDispatcher(session)
    dispatcher.dispatch({'type': MSG_TYPE_SESSION_END, 'reason': 'client_restart',
                         'detail': {'command': 'relaunch_instance'}})
    assert ctx.client_session_end['detail']['command'] == 'relaunch_instance'
    db, store = _new_store(tmp_path)
    item = _complete_session(store, client_end=ctx.client_session_end)
    assert item['termination_reason'] == 'client_restart'
    assert item['connection_state'] == 'offline'
    assert item['termination_detail'] == {'command': 'relaunch_instance'}
    db.close_thread_connection()


def test_server_disconnect_keeps_original_operator_command():
    from server.connection.client_session import ClientSession
    ctx = ClientSessionContext()
    session = SimpleNamespace(context=ctx)
    ClientSession.note_server_disconnect(session, 'disconnect')
    ClientSession.note_server_disconnect(session, 'kill_instance')
    assert ctx.server_disconnect_request['command'] == 'disconnect'


def test_server_requested_detail_uses_original_intent(tmp_path):
    _, store = _new_store(tmp_path)
    item = _complete_session(store, request={'at': time.monotonic(), 'command': 'disconnect'},
                             failure={'reason': 'connection_lost', 'detail': {}})
    assert item['termination_reason'] == 'server_requested_disconnect'
    assert item['connection_state'] == 'offline'
    assert item['termination_detail'] == {'command': 'disconnect'}


def test_client_report_can_include_command():
    client = ServerConnection()
    try:
        captured = []
        client.send = captured.append
        client.report_session_end('client_exit', command='kill_instance')
        assert captured == [{'type': MSG_TYPE_SESSION_END, 'reason': 'client_exit',
                             'detail': {'command': 'kill_instance'}}]
    finally:
        client.close()
