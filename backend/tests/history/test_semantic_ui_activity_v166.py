"""Persist one semantic Activity per dispatched UI operation and actual Client result."""

import json
from types import SimpleNamespace, ModuleType
from unittest.mock import patch
import sys

import pytest

from core.protocol.message_types import MSG_TYPE_PTY_OPEN, MSG_TYPE_PTY_CLOSE, MSG_TYPE_SCREEN_OPEN, MSG_TYPE_SCREEN_CLOSE
from server.application.clipboard.clipboard_session_service import ClipboardSessionService
_config = ModuleType('server.config.config')
_config.COMMAND_HISTORY_RECENT_LIMIT = 100
_config.COMMAND_HISTORY_PAGE_SIZE = 50
_config.COMMAND_HISTORY_MAX_PAGE_SIZE = 200
_config.COMMAND_HISTORY_MAX_OUTPUT_RECORD_CHARS = 65536
_config.COMMAND_HISTORY_MAX_OUTPUT_RECORDS = 256
# Isolate history from unrelated Flask admin configuration in the test environment.
with patch.dict(sys.modules, {'server.config.config': _config}):
    from server.application.history.activity_coordinator import ActivityCoordinator
    from server.application.history.command_dispatch_adapter import CommandDispatchAdapter
    from server.application.history import control_activity
    from server.application.history.lifecycle_adapter import LifecycleAdapter
    from server.application.history.activity_bindings import process_bindings, clipboard_bindings
    from server.application.history.activity_definitions import ActivityKind
    from server.application.history.history_store import CommandHistoryStore
from server.application.screen.screen_view_session_service import ScreenViewSessionService
from server.application.terminal.pty_session_service import PtySessionService
from server.application.web.process_control_api import WebProcessControlApi
from server.application.web.terminal_api import WebTerminalApi
from server.application.web.screen_view_api import WebScreenViewApi
from server.application.execution.remote_execution_service import RemoteExecutionService
from server.application.web.clipboard_api import WebClipboardApi
from server.persistence.rch_database import RchDatabase


class Connection:
    def __init__(self):
        self.session_info = SimpleNamespace(machine_id='machine-1', client_id='client-1')
        self.sent = []
        self.callback = None
        self.fail = False
        self.tracker = None
        self.context = SimpleNamespace()
        from server.connection.runtime.session_runtime import ClientSessionRuntime
        from server.connection.channel.session_command_channel import ClientSessionCommandChannel
        self.runtime = ClientSessionRuntime()
        self.channel = ClientSessionCommandChannel(self)
        self.acquire_foreground_task = self.runtime.acquire_foreground_task
        self.release_foreground_task = self.runtime.release_foreground_task

    def send_cancel(self, request_id):
        return self.channel.send_cancel(request_id)

    def send_command(self, *args, **kwargs):
        return self.channel.send_command(*args, **kwargs)

    def respond(self, request, status, result):
        self.runtime.pending_results.deliver(request['id'], status, result, 1)
        self.tracker.received(self, {'type': 'result', 'id': request['id'], 'status': status, 'eof': 1, 'data': result if isinstance(result, dict) else {}, 'text': result if isinstance(result, str) else ''})

    def send(self, payload):
        def transport_send(data):
            if self.fail:
                raise OSError('disconnected before dispatch')
            self.sent.append(data)
            if self.callback:
                self.callback(data)
        if self.tracker:
            return self.tracker.dispatch(self, payload, transport_send)
        return transport_send(payload)


def make_service(server, conn, service_class):
    """Test the production dispatch boundary with a synchronous Client ACK."""
    service = service_class(server)
    if service_class is ClipboardSessionService:
        return server.command_adapter.instrument(service, clipboard_bindings())
    else:
        is_pty = service_class is PtySessionService
        prefix = 'pty' if is_pty else 'screen'
        id_key = 'pty_session_id' if is_pty else 'screen_session_id'
        name_map = {'handle_client_opened': f'{prefix}_opened',
                    'handle_client_closed': f'{prefix}_closed',
                    'handle_client_error': f'{prefix}_error'}

    for name, event_type in name_map.items():
        original = getattr(service, name)
        def observed(*args, _original=original, _event_type=event_type, **kwargs):
            result = _original(*args, **kwargs)
            data = {'type': _event_type}
            data[id_key] = args[0]
            if _event_type == 'pty_opened':
                data['shell'] = kwargs.get('shell') or (args[1] if len(args) > 1 else '')
            if _event_type == 'pty_closed':
                data['exit_code'] = kwargs.get('exit_code', args[1] if len(args) > 1 else 0)
            if _event_type.endswith('_error'):
                data['message'] = args[1] if len(args) > 1 else ''
            conn.tracker.received(conn, data)
            return result
        setattr(service, name, observed)

    original_disconnect = service.handle_client_disconnected
    def disconnected(*args, **kwargs):
        result = original_disconnect(*args, **kwargs)
        conn.tracker.disconnected(conn)
        return result
    service.handle_client_disconnected = disconnected
    return service


@pytest.fixture
def setup_history(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = CommandHistoryStore(db)
    history = ActivityCoordinator(store)
    conn = Connection()
    tracker = LifecycleAdapter(history)
    conn.tracker = tracker
    server = SimpleNamespace(
        command_history=store,
        activity_coordinator=history,
        lifecycle_adapter=tracker,
        get_target_connection_by_client_id=lambda client_id: conn,
    )
    server.command_adapter = CommandDispatchAdapter(history, server.get_target_connection_by_client_id)
    conn.context.command_dispatch_adapter = server.command_adapter
    conn.context.activity_coordinator = history
    conn.bind_history_entry = conn.runtime.bind_history_entry
    conn.get_history_entry_id = conn.runtime.get_history_entry_id
    conn.clear_history_entry = conn.runtime.clear_history_entry
    yield server, conn
    db.close_thread_connection()


def entries(server):
    return server.command_history.view_service.get_execution_history_page('machine-1')['items']


def output_details(row):
    details = {}
    for record in row['result']['output_records']:
        try:
            value = json.loads(record['text'])
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            details.update(value)
    return details


def wire_command(text):
    return {'type': 'command', 'id': 1, 'text': text}


@pytest.mark.parametrize('service_class,open_type,close_type,id_key,open_callback,close_callback', [
    (PtySessionService, MSG_TYPE_PTY_OPEN, MSG_TYPE_PTY_CLOSE, 'pty_session_id',
     'handle_client_opened', 'handle_client_closed'),
    (ScreenViewSessionService, MSG_TYPE_SCREEN_OPEN, MSG_TYPE_SCREEN_CLOSE, 'screen_session_id',
     'handle_client_opened', 'handle_client_closed'),
])
def test_ui_sessions_confirm_client_open_close_and_dedupe(setup_history, service_class, open_type, close_type,
                                                          id_key, open_callback, close_callback):
    server, conn = setup_history
    service = make_service(server, conn, service_class)

    def respond(payload):
        if payload['type'] == open_type:
            getattr(service, open_callback)(payload[id_key])
        elif payload['type'] == close_type:
            getattr(service, close_callback)(payload[id_key])
    # A Client can ACK synchronously before the Server's send() call returns.
    conn.callback = respond
    created = service.create_session('client-1')
    sid = created[id_key]
    assert [(e['action'], e['status']) for e in entries(server)] == [('session', 'running')]
    assert output_details(entries(server)[0])['type'].endswith('_opened')
    if service_class is PtySessionService:
        api = server.lifecycle_adapter.instrument_closes(WebTerminalApi(service), kind=ActivityKind.PTY,
            method="close_pty_session", identifier="pty_session_id",
            reason=lambda a: "shell_switched" if a["reason"] == "switch_shell" else "user_closed" if a["user_initiated"] else "viewer_disconnected")
    else:
        api = server.lifecycle_adapter.instrument_closes(WebScreenViewApi(service), kind=ActivityKind.SCREEN_VIEW,
            method="close_screen_view", identifier="screen_session_id",
            reason=lambda a: "user_closed" if a["user_initiated"] else "viewer_disconnected")
    if service_class is PtySessionService:
        api.close_pty_session(sid, user_initiated=True)
        api.close_pty_session(sid, user_initiated=True)
    else:
        api.close_screen_view(sid, user_initiated=True)
        api.close_screen_view(sid, user_initiated=True)
    assert [(e['action'], e['status']) for e in entries(server)] == [('session', 'success')]
    assert output_details(entries(server)[0])['end_reason'] == 'user_closed'
    assert entries(server)[0]['finished_at']
    assert len([m for m in conn.sent if m['type'] == close_type]) == 1
    assert server.command_history.quick_store.list_recents('machine-1') == []


def test_automatic_close_never_creates_activity(setup_history):
    server, conn = setup_history
    pty = make_service(server, conn, PtySessionService)
    conn.callback = lambda payload: pty.handle_client_opened(payload['pty_session_id']) if payload['type'] == MSG_TYPE_PTY_OPEN else None
    sid = pty.create_session('client-1')['pty_session_id']
    pty.close_session(sid)
    pty.handle_client_closed(sid)
    assert [(e['kind'], e['action'], e['status']) for e in entries(server)] == [('pty', 'session', 'success')]


@pytest.mark.parametrize('service_class,id_key,open_type,opened,closed', [
    (PtySessionService, 'pty_session_id', MSG_TYPE_PTY_OPEN, 'handle_client_opened', 'handle_client_closed'),
    (ScreenViewSessionService, 'screen_session_id', MSG_TYPE_SCREEN_OPEN, 'handle_client_opened', 'handle_client_closed'),
])
def test_automatic_session_cleanup_is_not_an_activity(setup_history, service_class, id_key, open_type, opened, closed):
    server, conn = setup_history
    service = make_service(server, conn, service_class)
    conn.callback = lambda payload: getattr(service, opened)(payload[id_key]) if payload['type'] == open_type else None
    sid = service.create_session('client-1')[id_key]
    service.close_session(sid, user_initiated=False)
    getattr(service, closed)(sid)
    assert [(e['action'], e['status']) for e in entries(server)] == [('session', 'success')]


def test_clipboard_timeout_finishes_dispatched_activity(setup_history):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)
    service._target.REQUEST_TIMEOUT_SECONDS = 0.01
    with pytest.raises(TimeoutError, match='timed out'):
        service.set_clipboard('client-1', {'kind': 'text', 'text': 'never echoed'}, action='set_text')
    assert [(e['kind'], e['status']) for e in entries(server)] == [('clipboard', 'timed_out')]


def process_execution(server, conn, *, dispatch=True, fail=False):
    """Exercise the real RemoteExecutionService history boundary."""
    execution = RemoteExecutionService(server)
    if not dispatch:
        def fail_before_dispatch(*args, **kwargs):
            raise RuntimeError('Client command failed')
        execution.command_stream_service.stream_command = fail_before_dispatch
    else:
        def reply(request):
            result = 'Client command failed' if fail else ({'message': 'terminated'} if request.get('domain') == 'process' else 'terminated')
            conn.respond(request, 0 if fail else 1, result)
        conn.callback = reply
    return execution


def test_process_pre_dispatch_and_dispatched_errors_do_not_duplicate(setup_history):
    server, conn = setup_history
    api = server.command_adapter.instrument(WebProcessControlApi(server, process_execution(server, conn, dispatch=False, fail=True)), process_bindings())
    with pytest.raises(RuntimeError, match='failed'):
        api.kill_process('client-1', 88)
    assert entries(server) == []
    api = server.command_adapter.instrument(WebProcessControlApi(server, process_execution(server, conn, dispatch=True, fail=True)), process_bindings())
    with pytest.raises(RuntimeError, match='failed'):
        api.kill_app('client-1', 89, 'Safari')
    assert [(e['kind'], e['action'], e['status']) for e in entries(server)] == [('process', 'kill', 'error')]
    assert entries(server)[0]['invocation'] == {}
    assert entries(server)[0]['resolved']['payload'] == {'pid': 89}
    assert entries(server)[0]['summary'] == 'Kill app Safari (PID 89)'


def test_session_error_and_disconnect_finalize_only_dispatched_operations(setup_history):
    server, conn = setup_history
    screen = make_service(server, conn, ScreenViewSessionService)
    sid = screen.create_session('client-1')['screen_session_id']
    assert entries(server)[0]['status'] == 'running'
    screen.handle_client_disconnected('client-1')
    assert entries(server)[0]['status'] == 'interrupted'

    conn.fail = True
    with pytest.raises(OSError, match='disconnected'):
        screen.create_session('client-1')
    assert len(entries(server)) == 1


def test_clipboard_set_records_original_payload_and_get_is_optional(setup_history):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)

    def respond(payload):
        conn.respond(payload, 1, {'kind': 'text'})
    conn.callback = respond
    result = service.set_clipboard('client-1', {'kind': 'text', 'text': 'SUPER SECRET'}, action='set_text')
    assert result == {'kind': 'text'}
    entry = entries(server)[0]
    assert (entry['kind'], entry['action'], entry['status']) == ('clipboard', 'set', 'success')
    assert entry['invocation'] == {}
    assert entry['resolved']['payload']['text'] == 'SUPER SECRET'

    service.get_clipboard('client-1')
    assert len(entries(server)) == 1


def test_clipboard_error_and_send_failure_are_distinct(setup_history):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)
    conn.callback = lambda payload: conn.respond(payload, 0, 'Denied')
    with pytest.raises(RuntimeError, match='Denied'):
        service.set_clipboard('client-1', {'kind': 'text', 'text': 'private'}, action='set_text')
    assert entries(server)[0]['status'] == 'error'
    conn.fail = True
    with pytest.raises(OSError, match='disconnected'):
        service.set_clipboard('client-1', {'kind': 'text', 'text': 'private'}, action='set_text')
    assert len(entries(server)) == 1


def test_process_kill_emits_semantic_record_only(setup_history):
    server, conn = setup_history
    api = server.command_adapter.instrument(WebProcessControlApi(server, process_execution(server, conn)), process_bindings())
    assert api.kill_process('client-1', 123, 'chrome.exe')['message'] == 'terminated'
    assert api.kill_app('client-1', 456, 'Safari')['message'] == 'terminated'
    assert sorted((e['kind'], e['action'], e['status'], e['resolved']['payload']['pid']) for e in entries(server)) == [
        ('process', 'kill', 'success', 123), ('process', 'kill', 'success', 456),
    ]
    assert {e['summary'] for e in entries(server)} == {'Kill app Safari (PID 456)', 'Kill process chrome.exe (PID 123)'}
    assert all(e['resolved'] in conn.sent and e['invocation'] == {} for e in entries(server))


def test_pty_shell_switch_ends_one_session_without_close_entry(setup_history):
    server, conn = setup_history
    pty = make_service(server, conn, PtySessionService)
    conn.callback = lambda msg: (
        pty.handle_client_opened(msg['pty_session_id'], shell='/bin/bash')
        if msg['type'] == MSG_TYPE_PTY_OPEN else
        pty.handle_client_closed(msg['pty_session_id'], exit_code=0)
        if msg['type'] == MSG_TYPE_PTY_CLOSE else None
    )
    first = pty.create_session('client-1')['pty_session_id']
    api = server.lifecycle_adapter.instrument_closes(WebTerminalApi(pty), kind=ActivityKind.PTY,
        method='close_pty_session', identifier='pty_session_id',
        reason=lambda a: 'shell_switched' if a['reason'] == 'switch_shell' else 'user_closed')
    api.close_pty_session(first, reason='switch_shell')
    second = pty.create_session('client-1', shell='/bin/zsh')['pty_session_id']
    assert first != second
    rows = entries(server)
    assert len(rows) == 2
    assert {(e['action'], e['status']) for e in rows} == {('session', 'running'), ('session', 'success')}
    closed = next(e for e in rows if e['status'] == 'success')
    assert output_details(closed)['end_reason'] == 'shell_switched'
    assert output_details(closed)['shell'] == '/bin/bash'
    assert output_details(closed)['exit_code'] == 0
    assert all(e['finished_at'] is None for e in rows if e['status'] == 'running')


def test_pty_natural_exit_and_screen_disconnect_are_single_terminal_updates(setup_history):
    server, conn = setup_history
    pty = make_service(server, conn, PtySessionService)
    conn.callback = lambda msg: pty.handle_client_opened(msg['pty_session_id']) if msg['type'] == MSG_TYPE_PTY_OPEN else None
    pid = pty.create_session('client-1')['pty_session_id']
    pty.handle_client_closed(pid, exit_code=42)
    pty.handle_client_closed(pid, exit_code=42)
    row = entries(server)[0]
    assert (row['status'], output_details(row)['end_reason'], output_details(row)['exit_code']) == ('success', 'exited', 42)
    assert len(entries(server)) == 1

    screen = make_service(server, conn, ScreenViewSessionService)
    conn.callback = lambda msg: screen.handle_client_opened(msg['screen_session_id']) if msg['type'] == MSG_TYPE_SCREEN_OPEN else None
    screen.create_session('client-1')
    screen.handle_client_disconnected('client-1')
    rows = entries(server)
    assert len(rows) == 2
    interrupted = next(e for e in rows if e['kind'] == 'screen_view')
    assert interrupted['status'] == 'interrupted'
    assert output_details(interrupted)['end_reason'] == 'connection_lost'


def test_restart_marks_only_orphaned_sessions_interrupted(tmp_path):
    path = str(tmp_path / 'rch.db')
    db = RchDatabase(path)
    old_store = CommandHistoryStore(db)
    history = ActivityCoordinator(old_store)
    conn = Connection()
    tracker = LifecycleAdapter(history)
    conn.tracker = tracker
    server = SimpleNamespace(command_history=old_store, activity_coordinator=history,
                             lifecycle_adapter=tracker,
                             get_target_connection_by_client_id=lambda client_id: conn)
    pty = make_service(server, conn, PtySessionService)
    conn.callback = lambda msg: pty.handle_client_opened(msg['pty_session_id'])
    pty.create_session('client-1')
    assert entries(server)[0]['status'] == 'running'
    db.close_thread_connection()
    restarted_db = RchDatabase(path)
    restarted = CommandHistoryStore(restarted_db)
    row = restarted.view_service.get_execution_history_page('machine-1')['items'][0]
    assert row['status'] == 'interrupted'
    assert row['result']['output_records'][-1]['text'] == 'Server restarted'
    assert row['finished_at']
    restarted_db.close_thread_connection()


def test_web_clipboard_set_records_full_text_and_file_request(setup_history):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)
    api = WebClipboardApi(service, None)
    conn.callback = lambda msg: conn.respond(msg, 1, {})
    text = 'Hello\n' + 'A' * 3000
    api.set_text('client-1', text)
    entry = entries(server)[0]
    assert entry['invocation'] == {}
    assert entry['resolved']['payload'] == {'kind': 'text', 'text': text}
    api._set_files_payload('client-1', [{'type':'file','name':'report.pdf','url':'/secret/token'}],
                           ['report.pdf', r'folder\nested.txt'], action='set_files')
    files = next(e for e in entries(server) if e['resolved']['payload']['kind'] == 'files')
    assert files['invocation'] == {}
    assert files['resolved'] == conn.sent[-1]
    assert '/secret/token' in str(files['resolved'])


def test_web_clipboard_image_records_actual_transfer_description(setup_history, tmp_path):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)
    staged = tmp_path / 'screenshot.png'
    staged.write_bytes(b'1234567890')
    class Artifacts:
        def create_upload_temp_file(self, upload):
            return str(staged), 'screenshot.png'
        def build_upload_temp_download_relative_url(self, temp_path):
            return '/secret/signed-download'
        def cleanup_upload_temp_file(self, temp_path):
            pass
    api = WebClipboardApi(service, Artifacts())
    conn.callback = lambda msg: conn.respond(msg, 1, {})
    api.set_image('client-1', SimpleNamespace(filename='screenshot.png'))
    entry = entries(server)[0]
    assert entry['invocation'] == {}
    assert entry['resolved'] == conn.sent[-1]
    assert entry['resolved']['payload']['kind'] == 'image'
    assert '/secret/signed-download' in str(entry['resolved'])


def test_process_business_layer_has_no_history_control_and_normal_execution_unmodified(setup_history):
    from pathlib import Path
    server, conn = setup_history
    api = server.command_adapter.instrument(WebProcessControlApi(server, process_execution(server, conn)), process_bindings())
    assert api.kill_process('client-1', 5, 'A' * 200)['message'] == 'terminated'
    assert entries(server)[0]['summary'] == f"Kill process {'A' * 160} (PID 5)"
    assert entries(server)[0]['resolved']['payload'] == {'pid': 5}
    source = Path(__file__).parents[2] / 'server/application/web/process_control_api.py'
    assert 'command_history_orchestrator' not in source.read_text()
    execution = process_execution(server, conn)
    assert execution.run_foreground_text_command('client-1', 'uptime') == 'terminated'
    assert len(entries(server)) == 1


def test_client_session_transport_hooks_own_early_ack_and_close(setup_history):
    """Exercise the real ClientSession dispatch path, not only the session services."""
    from server.connection.client_session import ClientSession
    from core.protocol.message_types import MSG_TYPE_PTY_OPENED, MSG_TYPE_PTY_CLOSED

    server, _ = setup_history

    class Transport:
        address = ('127.0.0.1', 1111)

        def __init__(self):
            self.session = None
            self.sent = []

        def send(self, data):
            self.sent.append(data)
            if data['type'] == MSG_TYPE_PTY_OPEN:
                # Client responds before socket send() returns.
                self.session.handle_received_message({
                    'type': MSG_TYPE_PTY_OPENED, 'pty_session_id': data['pty_session_id'],
                    'shell': '/bin/zsh',
                })
            elif data['type'] == MSG_TYPE_PTY_CLOSE:
                self.session.handle_received_message({
                    'type': MSG_TYPE_PTY_CLOSED, 'pty_session_id': data['pty_session_id'],
                    'exit_code': 0,
                })

    transport = Transport()
    conn = ClientSession(transport)
    conn.session_info.machine_id = 'machine-1'
    conn.session_info.client_id = 'client-1'
    transport.session = conn
    conn.context.on_client_message_send = server.lifecycle_adapter.dispatch
    conn.context.on_client_message_received = server.lifecycle_adapter.received
    conn.context.on_pty_opened = lambda *args: None
    conn.context.on_pty_closed = lambda *args: None

    conn.send({'type': MSG_TYPE_PTY_OPEN, 'pty_session_id': 'early', 'shell': ''})
    row = entries(server)[0]
    assert row['status'] == 'running'
    assert output_details(row)['shell'] == '/bin/zsh'
    server.lifecycle_adapter.close_call(ActivityKind.PTY, 'early', 'shell_switched',
        lambda: conn.send({'type': MSG_TYPE_PTY_CLOSE, 'pty_session_id': 'early'}))
    row = entries(server)[0]
    assert (row['status'], output_details(row)['end_reason']) == ('success', 'shell_switched')
    assert len(entries(server)) == 1


def test_read_only_and_input_messages_skip_activity(setup_history):
    server, conn = setup_history
    for message in (
        {'type': 'control', 'domain': 'clipboard', 'action': 'get', 'id': 42, 'payload': {'mode': 'content'}},
        {'type': 'pty_input', 'pty_session_id': 'p1', 'data': 'ls'},
        {'type': 'pty_resize', 'pty_session_id': 'p1', 'cols': 80},
        {'type': 'screen_config', 'screen_session_id': 's1', 'fps': 12},
        {'type': 'screen_input', 'screen_session_id': 's1', 'event': {}},
    ):
        conn.send(message)
    assert entries(server) == []


def test_same_session_identifier_is_scoped_to_original_connection(setup_history):
    server, first = setup_history
    second = Connection()
    second.tracker = server.lifecycle_adapter
    first.send({'type': MSG_TYPE_PTY_OPEN, 'pty_session_id': 'same'})
    second.send({'type': MSG_TYPE_PTY_OPEN, 'pty_session_id': 'same'})
    server.lifecycle_adapter.received(first, {'type': 'pty_opened', 'pty_session_id': 'same'})
    server.lifecycle_adapter.received(second, {'type': 'pty_opened', 'pty_session_id': 'same'})
    server.lifecycle_adapter.disconnected(first)
    rows = entries(server)
    assert len(rows) == 2
    assert sorted(row['status'] for row in rows) == ['interrupted', 'running']
    assert output_details(next(row for row in rows if row['status'] == 'interrupted'))['end_reason'] == 'connection_lost'


def test_activity_storage_error_does_not_cancel_transport(setup_history):
    server, conn = setup_history
    with patch.object(server.activity_coordinator, 'prepare',
                      side_effect=OSError('activity database busy')):
        conn.send({'type': MSG_TYPE_PTY_OPEN, 'pty_session_id': 'still-sent'})
    assert conn.sent[0]['pty_session_id'] == 'still-sent'
    assert entries(server) == []


def test_early_failed_send_discarded_even_if_ack_arrived(setup_history):
    server, conn = setup_history
    original = conn.send

    def interrupted_send(message, **kwargs):
        def transport(data):
            server.lifecycle_adapter.received(conn, {
                'type': 'pty_opened', 'pty_session_id': data['pty_session_id'],
            })
            raise OSError('failed while sending')
        return server.lifecycle_adapter.dispatch(conn, message, transport, **kwargs)

    conn.send = interrupted_send
    with pytest.raises(OSError, match='failed while sending'):
        conn.send({'type': MSG_TYPE_PTY_OPEN, 'pty_session_id': 'lost'})
    assert entries(server) == []


@pytest.mark.parametrize('kind', (
    'command', 'alias', 'script', 'remote_files', 'transfer', 'external_tool',
    'job', 'pty', 'screen_view', 'clipboard', 'process',
))
def test_all_activity_kinds_share_one_dispatch_commit(setup_history, kind):
    from server.application.history.activity_definitions import ActivityOperation
    server, conn = setup_history
    activity_id = server.activity_coordinator.prepare(conn, ActivityOperation(kind, 'run', {'id': kind}))
    assert entries(server) == []  # The intention alone never creates a database row.
    assert server.activity_coordinator.dispatch(conn, activity_id, data=wire_command('probe'))
    assert [(row['kind'], row['status']) for row in entries(server)] == [(kind, 'running')]
    server.activity_coordinator.finish(conn, activity_id, True)
    assert [(row['kind'], row['status']) for row in entries(server)] == [(kind, 'success')]


def test_declarative_bindings_keep_remote_file_and_job_services_history_free(setup_history):
    from server.application.history.activity_bindings import remote_file_bindings, job_bindings
    server, conn = setup_history
    adapter = server.command_adapter

    class RemoteFiles:
        def delete_paths(self, client_id, paths, origin='web_api'):
            conn.callback = lambda request: conn.respond(request, 1, {'message':'deleted'})
            list(conn.send_command('', type='control', domain='remote_files', action='delete_paths', payload={'paths':paths}))
            return {'message': 'deleted'}

        def list_directory(self, client_id):
            return {'items': []}

    class Jobs:
        def start_job(self, client_id, job_name, params=None, execution_mode='inproc', origin='web_api'):
            conn.callback = lambda request: conn.respond(request, 1, {'job_id':'job-1'})
            list(conn.send_command('', type='control', domain='job', action='start', payload={'job_name':'check'}))
            return {'job_id': 'job-1', 'message': 'started'}

    remote = adapter.instrument(RemoteFiles(), remote_file_bindings())
    assert remote.list_directory('client-1') == {'items': []}
    assert not entries(server)
    assert remote.delete_paths('client-1', ['/tmp/test'])['message'] == 'deleted'
    assert entries(server)[0]['kind'] == 'remote_files'

    jobs = adapter.instrument(Jobs(), job_bindings())
    jobs.start_job('client-1', 'check')
    assert {(row['kind'], row['status']) for row in entries(server)} == {
        ('remote_files', 'success'), ('job', 'success'),
    }


def test_external_tool_exec_and_cli_job_result_stay_inside_command_adapter(setup_history):
    from core.protocol.structured_arg_codec import encode_structured_arg
    from server.application.history.activity_definitions import ActivityOperation
    import json
    server, conn = setup_history
    adapter = server.command_adapter
    coordinator = server.activity_coordinator
    activity_id = coordinator.prepare(conn, ActivityOperation('command', 'invoke', {}, text='xt exec ffmpeg -version'))
    request = wire_command('external_tool_exec ' + encode_structured_arg({
        'exec_name': 'ffmpeg', 'package_id': 'ffmpeg',
    }))
    adapter.dispatch(conn, activity_id, request)
    row = entries(server)[0]
    assert row['kind'] == 'external_tool'
    assert row['invocation'] == {'command': 'xt exec ffmpeg -version'}
    assert row['resolved'] == request

    job_id = coordinator.prepare(conn, ActivityOperation('command', 'invoke', {}, text='job stop check'))
    cmd = {'job_key': 'check'}
    request = {'type': 'control', 'id': 2, 'domain': 'job', 'action': 'stop', 'payload': cmd}
    job_id = adapter.prepare_dispatch(conn, job_id, request)
    adapter.dispatch(conn, job_id, request)
    from core.protocol.job_control import build_job_control_result
    result = build_job_control_result('stop', 'stopped', job_id='job-1')
    from core.protocol.message_queue import ResultChunk
    assert list(adapter.observe_result(conn, job_id, request, [ResultChunk(1, result, 1)])) == [(1, result)]
    row = next(row for row in entries(server) if row['kind'] == 'job')
    assert row['resolved'] == request
    assert output_details(row)['job_id'] == 'job-1'
    assert {'type':'job','id':'job-1'} in row['references']
    assert row['invocation']['command'] == 'job stop check'


def test_transfer_adapter_tracks_repeated_transfers_and_not_browser_staging(setup_history):
    server, conn = setup_history
    transfer = {
        'transfer_id': 'transfer-1', 'client_id': 'client-1',
        'direction': 'server_to_client', 'filename': 'report.pdf',
        'state': 'running', 'total_bytes': 100, 'destination_path': '/tmp',
        'metadata': {'source': 'remote_file_upload', 'browser_stage': True},
    }
    service = SimpleNamespace(get_transfer=lambda tid: transfer if tid == transfer['transfer_id'] else None)
    server.lifecycle_adapter.bind_transfer_service(service)
    assert entries(server) == []  # Browser -> Server preparation is not a Client operation.
    conn.send({'type': 'transfer_start', 'transfer_id': 'transfer-1'})
    assert [(r['kind'], r['status']) for r in entries(server)] == [('transfer', 'running')]
    conn.send({'type': 'transfer_start', 'transfer_id': 'transfer-1'})  # Retries must not duplicate.
    transfer['state'] = 'completed'
    server.lifecycle_adapter.transfer_updated(transfer)
    assert len(entries(server)) == 1
    assert entries(server)[0]['status'] == 'success'

    transfer.update(transfer_id='transfer-2', state='running')
    conn.send({'type': 'transfer_start', 'transfer_id': 'transfer-2'})
    assert len(entries(server)) == 2
    transfer['state'] = 'failed'
    server.lifecycle_adapter.transfer_updated(transfer)
    assert sorted(row['status'] for row in entries(server)) == ['error', 'success']


def test_history_failures_do_not_block_declarative_business_dispatch(setup_history):
    from server.application.history.activity_bindings import process_bindings, clipboard_bindings
    server, conn = setup_history

    class Processes:
        def kill_process(self, client_id, pid, name=''):
            return {'message': 'terminated'}

    api = server.command_adapter.instrument(Processes(), process_bindings())
    with patch.object(server.activity_coordinator, 'prepare', side_effect=OSError('database locked')):
        assert api.kill_process('client-1', 101, 'worker') == {'message': 'terminated'}
    assert entries(server) == []


def test_artifact_reference_binding_uses_lifecycle_adapter_not_web_api(setup_history):
    server, conn = setup_history
    captured = {'calls': []}

    class Artifacts:
        def register_command_output_artifact(self, *, client_id, source_command_id=None, **kwargs):
            return {'artifact_id': 'file-1', 'original_name': 'report.txt'}

    conn.bind_history_entry = lambda cmd, entry_id: captured['calls'].append((cmd, entry_id))
    conn.get_history_entry_id = lambda command_id: captured['entry_id'] if command_id == 42 else ''
    operation = __import__('server.application.history.activity_definitions', fromlist=['ActivityOperation']).ActivityOperation
    activity_id = server.activity_coordinator.prepare(conn, operation('command', 'invoke', {}, text='saveout shell pwd'))
    captured['entry_id'] = activity_id
    server.activity_coordinator.dispatch(conn, activity_id, data=wire_command('shell pwd'))
    facade = server.lifecycle_adapter.instrument_artifacts(
        Artifacts(), server.get_target_connection_by_client_id,
    )
    result = facade.register_command_output_artifact(client_id='client-1', source_command_id=42)
    assert result['artifact_id'] == 'file-1'
    assert entries(server)[0]['files'][0]['artifact_id'] == 'file-1'


def test_terminal_upload_claims_transfer_activity_once(setup_history):
    """A Transfer start claims the terminal upload ID exactly once."""

    server, conn = setup_history
    candidate = server.command_adapter.prepare_command(conn, 'upload report.pdf', source='cli')
    transfer = {
        'transfer_id': 'upload-terminal', 'client_id': 'client-1',
        'direction': 'server_to_client', 'filename': 'report.pdf',
        'destination_path': '/tmp', 'total_bytes': 10, 'state': 'running',
        'metadata': {'source': 'cli', 'history_entry_id': candidate},
    }
    server.lifecycle_adapter.bind_transfer_service(SimpleNamespace(
        get_transfer=lambda transfer_id: transfer if transfer_id == 'upload-terminal' else None,
    ))
    server.command_adapter.bind_lifecycle_adapter(server.lifecycle_adapter)
    conn.send({'type': 'transfer_start', 'transfer_id': 'upload-terminal'})
    rows = entries(server)
    assert len(rows) == 1
    assert rows[0]['activity_id'] == candidate
    assert (rows[0]['kind'], rows[0]['action'], rows[0]['status']) == ('transfer', 'upload_files', 'running')
    assert rows[0]['invocation']['command'] == 'upload report.pdf'

    server.lifecycle_adapter.transfer_updated({**transfer, 'state': 'completed'})
    rows = entries(server)
    assert len(rows) == 1 and rows[0]['status'] == 'success'


@pytest.mark.parametrize('source', ['cli', 'web'])
@pytest.mark.parametrize('command,expected_action,wire', [
    ('xt instance start filebrowser-8080', 'start_instance', 'external_tool_start'),
    ('xt instance stop filebrowser-8080', 'stop_instance', 'external_tool_stop'),
    ('xt instance restart filebrowser-8080', 'restart_instance', 'external_tool_stop'),
    ('xt instance create pkg.module --id my-instance --start', 'create_instance', 'external_tool_instance_create'),
    ('xt package install package-1', 'install_package', 'external_tool_install'),
    ('xt package uninstall package-1', 'uninstall_package', 'external_tool_uninstall'),
])
def test_xt_cli_mutations_record_only_after_real_dispatch(setup_history, source, command, expected_action, wire):
    server, conn = setup_history
    adapter = server.command_adapter
    activity_id = adapter.prepare_command(conn, command, source=source)
    assert activity_id
    assert entries(server) == []

    # xt status/install/instance queries are read-only even when they reach Client.
    adapter.dispatch(conn, activity_id, wire_command('external_tool_status payload'))
    adapter.dispatch(conn, activity_id, wire_command('external_tool_instance_read payload'))
    assert entries(server) == []
    adapter.dispatch(conn, activity_id, wire_command(wire + ' payload'))
    rows = entries(server)
    assert len(rows) == 1
    assert (rows[0]['kind'], rows[0]['action'], rows[0]['status']) == (
        'external_tool', expected_action, 'running')
    assert rows[0]['invocation']['command'] == command
    assert 'payload' not in str(rows[0]['invocation'])

    # Restart/create --start may send a second mutating Client command: one activity only.
    adapter.dispatch(conn, activity_id, wire_command('external_tool_start payload'))
    assert len(entries(server)) == 1
    server.activity_coordinator.finish(conn, activity_id, True)
    assert entries(server)[0]['status'] == 'success'


@pytest.mark.parametrize('command', [
    'xt', 'xt help', 'xt package list', 'xt module list',
    'xt instance list', 'xt instance status filebrowser-8080',
    'xt instance logs filebrowser-8080', 'xt exec list', 'xt exec info ffmpeg',
    'xt exec which ffmpeg',
])
def test_xt_cli_queries_do_not_create_activity_even_with_client_preflight(setup_history, command):
    server, conn = setup_history
    adapter = server.command_adapter
    activity_id = adapter.prepare_command(conn, command, source='cli')
    adapter.dispatch(conn, activity_id, wire_command('external_tool_status payload'))
    server.activity_coordinator.finish(conn, activity_id, True)
    assert entries(server) == []


def test_xt_invalid_or_undispatched_command_does_not_create_activity(setup_history):
    server, conn = setup_history
    adapter = server.command_adapter
    for command in ('xt instance start missing-instance', 'xt instance create demo', 'xt package install missing'):
        activity_id = adapter.prepare_command(conn, command, source='cli')
        assert activity_id
        server.activity_coordinator.finish(conn, activity_id, False)
    assert entries(server) == []


def test_web_external_tool_mutation_keeps_existing_adapter_dispatch(setup_history):
    from server.application.history.activity_definitions import ActivityOperation
    server, conn = setup_history
    activity_id = server.activity_coordinator.prepare(conn, ActivityOperation(
        'external_tool', 'clear_package_cache', {'package_id': 'demo'}, origin='web_api',
    ))
    server.command_adapter.dispatch(conn, activity_id, wire_command('external_tool_clear_package_cache payload'))
    assert [(row['kind'], row['action']) for row in entries(server)] == [
        ('external_tool', 'clear_package_cache')
    ]


def test_xt_exec_actual_plan_retains_candidate_until_client_dispatch(setup_history):
    from core.protocol.structured_arg_codec import encode_structured_arg
    server, conn = setup_history
    adapter = server.command_adapter
    activity_id = adapter.prepare_command(conn, 'xt exec ffmpeg -version', source='cli')
    client_command = 'external_tool_exec ' + encode_structured_arg({
        'exec_name': 'ffmpeg', 'package_id': 'ffmpeg',
    })
    adapter.describe_plan(conn, activity_id, {'command': client_command, 'command_type': 'command'})
    assert entries(server) == []
    adapter.dispatch(conn, activity_id, wire_command(client_command))
    assert [(row['kind'], row['action']) for row in entries(server)] == [
        ('external_tool', 'run_exec')
    ]
    assert entries(server)[0]['invocation']['command'] == 'xt exec ffmpeg -version'


def test_independent_mutations_keep_existing_activity_without_rebinding_foreground(setup_history):
    from server.application.artifact.remote_file_service import WebRemoteFileService
    from server.application.history.activity_bindings import remote_file_bindings
    server, conn = setup_history
    conn.context.command_dispatch_adapter = server.command_adapter
    conn.context.activity_coordinator = server.activity_coordinator
    conn.bind_history_entry = conn.runtime.bind_history_entry
    conn.get_history_entry_id = conn.runtime.get_history_entry_id
    conn.clear_history_entry = conn.runtime.clear_history_entry
    conn.runtime.acquire_foreground_task('script', 'probe')
    conn.runtime.bind_command_execution(999)
    execution = RemoteExecutionService(server)
    files = server.command_adapter.instrument(WebRemoteFileService(execution, None), remote_file_bindings())
    processes = server.command_adapter.instrument(WebProcessControlApi(server, execution), process_bindings())
    def reply(payload):
        if payload['action'] == 'create_directory':
            conn.respond(payload, 1, 'Directory created')
        elif payload['action'] == 'kill':
            conn.respond(payload, 1, {'message':'terminated'})
        else:
            conn.respond(payload, 1, {'entries':[]})
    conn.callback = reply
    files.browse_directory('client-1', '/tmp')
    assert not entries(server)
    files.create_directory('client-1', '/tmp/test')
    processes.kill_process('client-1', 1234)
    assert {(e['kind'], e['status']) for e in entries(server)} == {('remote_files','success'), ('process','success')}
    assert conn.runtime.get_foreground_task()['command_id'] == 999
    assert not conn.runtime.pending_results._items
    conn.runtime.release_foreground_task(command='probe')


def test_control_catalog_records_every_action_by_policy(setup_history, monkeypatch):
    from core.protocol.control import ControlDomain, control_actions, action_spec, ActivityPolicy
    server, conn = setup_history
    conn.callback = lambda req: conn.respond(req, 1, {'message':'ok'})
    actions = [(domain, action) for domain in ControlDomain for action, _ in control_actions(domain)]
    assert len(actions) == 24
    monkeypatch.setattr(control_activity.config, 'RECORD_OPTIONAL_ACTIVITY', False, raising=False)
    for domain, action in actions:
        list(conn.send_command('', type='control', domain=domain, action=action, payload={}))
    assert {(r['kind'], r['action']) for r in entries(server)} == {
        (domain, action) for domain, action in actions if action_spec(domain, action).activity == ActivityPolicy.ALWAYS}
    assert len(entries(server)) == 15
    monkeypatch.setattr(control_activity.config, 'RECORD_OPTIONAL_ACTIVITY', True)
    for domain, action in actions:
        list(conn.send_command('', type='control', domain=domain, action=action, payload={}))
    assert len(entries(server)) == 39
    assert {(r['kind'], r['action']) for r in entries(server)} == set(actions)


def test_configuration_cli_and_control_share_policy_and_preserve_actual_values(setup_history, monkeypatch):
    from core.utils.configuration_cli import parse_configuration_request
    server, conn = setup_history
    adapter = server.command_adapter
    conn.callback = lambda req: conn.respond(req, 1, {'message':'SECRET_TOKEN'})
    def send_command(command):
        entry = adapter.prepare_command(conn, command, source='web')
        if command.startswith('set'):
            action, payload, _ = parse_configuration_request(command[3:].strip())
            domain = 'configuration'
        else:
            domain, action, payload = 'watchdog', 'status', {}
        list(conn.send_command('', type='control', domain=domain, action=action, payload=payload, history_entry_id=entry))
        server.activity_coordinator.finish(conn, entry, True)
    for command in ('set TOKEN SECRET_TOKEN', 'set --reset TOKEN', 'set --json', 'watchdog --json'):
        send_command(command)
    list(conn.send_command('', type='control', domain='configuration', action='set', payload={'key':'TOKEN','value':'SECRET_TOKEN'}))
    assert len(entries(server)) == 3
    assert {row['kind'] for row in entries(server)} == {'configuration'}
    assert 'SECRET_TOKEN' in str(entries(server))
    assert all(row['resolved']['payload']['key'] == 'TOKEN' for row in entries(server))
    monkeypatch.setattr(control_activity.config, 'RECORD_OPTIONAL_ACTIVITY', True, raising=False)
    for command in ('set --json', 'watchdog --json'):
        send_command(command)
    assert {(row['kind'],row['action']) for row in entries(server)} == {('configuration','get'),('configuration','set'),('configuration','reset'),('watchdog','status')}
    assert all(row['resolved'] in conn.sent for row in entries(server))


def test_control_terminal_eof_owns_status_and_inspect_uses_action_policy(setup_history):
    server, conn = setup_history
    def reply(req):
        conn.runtime.pending_results.deliver(req['id'], 0, '[WARNING] missing optional item', 0)
        conn.respond(req, 1, {'message':'Not approved'})
    conn.callback = reply
    rows = list(conn.send_command('', type='control', domain='script', action='run', payload={'script_name':'probe','params':{}}))
    assert [r.eof for r in rows] == [False, True]
    row = entries(server)[0]
    assert row['status'] == 'success'
    assert [r['eof'] for r in row['result']['output_records']] == [0,1]
    for action in ('paste_paths','extract_archive'):
        list(conn.send_command('', type='control', domain='remote_files', action=action, payload={'inspect':True}))
    assert len(entries(server)) == 3
    assert {row['action'] for row in entries(server) if row['resolved']['payload'].get('inspect')} == {'paste_paths','extract_archive'}
    from server.application.command.command_execution_pipeline import CommandExecutionPipeline
    from server.application.tasks.task_status import TaskStreamSummary
    from server.application.tasks.task_runner import WebTaskRunner
    # Test actual task result reduction without a browser or socket publisher.
    runner = object.__new__(WebTaskRunner)
    runner._publish_stream_chunk = lambda *args: None
    summary = TaskStreamSummary()
    for row in rows:
        runner._record_task_event(None, CommandExecutionPipeline.build_result_event(row), summary)
    assert summary.resolve_final_status(cancel_requested=True) == 'success'


@pytest.mark.parametrize('terminal,expected', [({'event_type':'cancelled','text':'cancelled'},'cancelled'),({'failure_reason':'timed_out','text':'timeout'},'timed_out'),(None,'interrupted'),('failure','error')])
def test_control_terminal_failure_reasons(setup_history, terminal, expected):
    server, conn = setup_history
    conn.callback = lambda req: conn.respond(req, 0, terminal)
    list(conn.send_command('', type='control', domain='process', action='kill', payload={'pid':42}))
    assert entries(server)[0]['status'] == expected
