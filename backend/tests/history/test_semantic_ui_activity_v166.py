"""Persist one semantic Activity per dispatched UI operation and actual Client result."""

from types import SimpleNamespace, ModuleType
from unittest.mock import patch
import sys

import pytest

from core.protocol.message_types import MSG_TYPE_CLIPBOARD_SET, MSG_TYPE_PTY_OPEN, MSG_TYPE_PTY_CLOSE, MSG_TYPE_SCREEN_OPEN, MSG_TYPE_SCREEN_CLOSE
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
    from server.application.history.lifecycle_adapter import LifecycleAdapter
    from server.application.history.activity_bindings import process_bindings
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
        self.context = SimpleNamespace(on_client_request_failed=None)

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
        name_map = {'handle_client_result': 'clipboard_result'}
        id_key = 'clipboard_request_id'
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
            if _event_type == 'clipboard_result':
                data.update(args[1])
            else:
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
    return server.lifecycle_adapter.instrument_clipboard(service) if service_class is ClipboardSessionService else service


@pytest.fixture
def setup_history(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = CommandHistoryStore(db)
    history = ActivityCoordinator(store)
    conn = Connection()
    tracker = LifecycleAdapter(history)
    conn.tracker = tracker
    conn.context.on_client_request_failed = tracker.request_failed
    server = SimpleNamespace(
        command_history=store,
        activity_coordinator=history,
        lifecycle_adapter=tracker,
        get_target_connection_by_client_id=lambda client_id: conn,
    )
    server.command_adapter = CommandDispatchAdapter(history, server.get_target_connection_by_client_id)
    yield server, conn
    db.close_thread_connection()


def entries(server):
    return server.command_history.view_service.get_execution_history_page('machine-1')['items']


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
    assert entries(server)[0]['resolved'].get('opened_at')
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
    assert entries(server)[0]['resolved']['end_reason'] == 'user_closed'
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
    service.REQUEST_TIMEOUT_SECONDS = 0
    with pytest.raises(TimeoutError, match='timed out'):
        service.set_clipboard('client-1', {'kind': 'text', 'text': 'never echoed'}, action='set_text')
    assert [(e['kind'], e['status']) for e in entries(server)] == [('clipboard', 'timed_out')]


def process_execution(server, conn, *, dispatch=True, fail=False):
    """Exercise the real RemoteExecutionService history boundary."""
    execution = RemoteExecutionService.__new__(RemoteExecutionService)
    execution.command_stream_service = SimpleNamespace(get_connection=lambda target: conn)

    def run(target, command, **kwargs):
        if dispatch:
            server.command_adapter.dispatch(conn, kwargs['history_entry_id'], command, 'command')
        if fail:
            raise RuntimeError('Client command failed')
        return 'terminated'

    execution.foreground_execution_service = SimpleNamespace(run_foreground_text_command=run)
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
    assert [(e['kind'], e['action'], e['status']) for e in entries(server)] == [('process', 'kill_app', 'error')]
    assert entries(server)[0]['invocation']['arguments'] == {'pid': 89, 'name': 'Safari'}


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


def test_clipboard_set_tracks_results_without_sensitive_payload_and_get_is_read_only(setup_history):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)

    def respond(payload):
        service.handle_client_result('client-1', {
            'clipboard_request_id': payload['clipboard_request_id'],
            'ok': True, 'payload': {'kind': 'text'},
        })
    conn.callback = respond
    result = service.set_clipboard('client-1', {'kind': 'text', 'text': 'SUPER SECRET'}, action='set_text')
    assert result == {'kind': 'text'}
    entry = entries(server)[0]
    assert (entry['kind'], entry['action'], entry['status']) == ('clipboard', 'set_text', 'success')
    assert entry['invocation']['arguments']['text'] == 'SUPER SECRET'

    service.get_clipboard('client-1')
    assert len(entries(server)) == 1


def test_clipboard_error_and_send_failure_are_distinct(setup_history):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)
    conn.callback = lambda payload: service.handle_client_result('client-1', {
        'clipboard_request_id': payload['clipboard_request_id'], 'ok': False, 'error': 'Denied',
    })
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
    assert sorted((e['kind'], e['action'], e['status'], e['invocation']['arguments']['pid']) for e in entries(server)) == [
        ('process', 'kill_app', 'success', 456), ('process', 'kill_process', 'success', 123),
    ]
    assert {e['invocation']['arguments']['name'] for e in entries(server)} == {'Safari', 'chrome.exe'}
    assert all(e['resolved'] == {'command_type': 'command'} for e in entries(server))


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
    assert closed['resolved']['end_reason'] == 'shell_switched'
    assert closed['resolved']['shell'] == '/bin/bash'
    assert closed['resolved']['exit_code'] == 0
    assert all(e['finished_at'] is None for e in rows if e['status'] == 'running')


def test_pty_natural_exit_and_screen_disconnect_are_single_terminal_updates(setup_history):
    server, conn = setup_history
    pty = make_service(server, conn, PtySessionService)
    conn.callback = lambda msg: pty.handle_client_opened(msg['pty_session_id']) if msg['type'] == MSG_TYPE_PTY_OPEN else None
    pid = pty.create_session('client-1')['pty_session_id']
    pty.handle_client_closed(pid, exit_code=42)
    pty.handle_client_closed(pid, exit_code=42)
    row = entries(server)[0]
    assert (row['status'], row['resolved']['end_reason'], row['resolved']['exit_code']) == ('success', 'exited', 42)
    assert len(entries(server)) == 1

    screen = make_service(server, conn, ScreenViewSessionService)
    conn.callback = lambda msg: screen.handle_client_opened(msg['screen_session_id']) if msg['type'] == MSG_TYPE_SCREEN_OPEN else None
    screen.create_session('client-1')
    screen.handle_client_disconnected('client-1')
    rows = entries(server)
    assert len(rows) == 2
    interrupted = next(e for e in rows if e['kind'] == 'screen_view')
    assert interrupted['status'] == 'interrupted'
    assert interrupted['resolved']['end_reason'] == 'connection_lost'


def test_restart_marks_only_orphaned_sessions_interrupted(tmp_path):
    path = str(tmp_path / 'rch.db')
    db = RchDatabase(path)
    old_store = CommandHistoryStore(db)
    history = ActivityCoordinator(old_store)
    conn = Connection()
    tracker = LifecycleAdapter(history)
    conn.tracker = tracker
    conn.context.on_client_request_failed = tracker.request_failed
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
    assert row['resolved']['end_reason'] == 'server_restarted'
    assert row['finished_at']
    restarted_db.close_thread_connection()


def test_web_clipboard_set_records_bounded_text_and_safe_files(setup_history):
    server, conn = setup_history
    service = make_service(server, conn, ClipboardSessionService)
    api = WebClipboardApi(service, None)
    conn.callback = lambda msg: service.handle_client_result('client-1', {
        'clipboard_request_id': msg['clipboard_request_id'], 'ok': True, 'payload': {},
    })
    text = 'Hello\n' + 'A' * 3000
    api.set_text('client-1', text)
    args = entries(server)[0]['invocation']['arguments']
    assert args['text'] == text[:2048]
    assert (args['length'], args['truncated']) == (len(text), True)

    # Server staging URLs may contain authentication tokens; they must not survive in history.
    api._set_files_payload('client-1', [{'type':'file','name':'report.pdf','url':'/secret/token'}],
                           ['report.pdf', r'folder\nested.txt'], action='set_files')
    files = next(e for e in entries(server) if e['action'] == 'set_files')
    assert files['invocation']['arguments'] == {
        'count': 2, 'names': ['report.pdf', 'nested.txt'], 'names_truncated': False,
    }
    assert '/secret/token' not in str(files)


def test_web_clipboard_image_records_file_metadata_only(setup_history, tmp_path):
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
    conn.callback = lambda msg: service.handle_client_result('client-1', {
        'clipboard_request_id': msg['clipboard_request_id'], 'ok': True, 'payload': {},
    })
    api.set_image('client-1', SimpleNamespace(filename='screenshot.png'))
    entry = entries(server)[0]
    assert entry['invocation']['arguments'] == {
        'filename': 'screenshot.png', 'mime_type': 'image/png', 'size_bytes': 10,
    }
    assert '/secret/signed-download' not in str(entry)


def test_process_business_layer_has_no_history_control_and_normal_execution_unmodified(setup_history):
    from pathlib import Path
    server, conn = setup_history
    api = server.command_adapter.instrument(WebProcessControlApi(server, process_execution(server, conn)), process_bindings())
    assert api.kill_process('client-1', 5, 'A' * 200)['message'] == 'terminated'
    assert len(entries(server)[0]['invocation']['arguments']['name']) == 160
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
    assert row['resolved']['shell'] == '/bin/zsh'
    server.lifecycle_adapter.close_call(ActivityKind.PTY, 'early', 'shell_switched',
        lambda: conn.send({'type': MSG_TYPE_PTY_CLOSE, 'pty_session_id': 'early'}))
    row = entries(server)[0]
    assert (row['status'], row['resolved']['end_reason']) == ('success', 'shell_switched')
    assert len(entries(server)) == 1


def test_read_only_and_input_messages_skip_activity(setup_history):
    server, conn = setup_history
    for message in (
        {'type': 'clipboard_get', 'clipboard_request_id': 'get-1', 'mode': 'content'},
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
    assert next(row for row in rows if row['status'] == 'interrupted')['resolved']['end_reason'] == 'connection_lost'


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
    'background_job', 'pty', 'screen_view', 'clipboard', 'process',
))
def test_all_activity_kinds_share_one_dispatch_commit(setup_history, kind):
    from server.application.history.activity_definitions import ActivityOperation
    server, conn = setup_history
    activity_id = server.activity_coordinator.prepare(conn, ActivityOperation(kind, 'run', {'id': kind}))
    assert entries(server) == []  # The intention alone never creates a database row.
    assert server.activity_coordinator.dispatch(conn, activity_id)
    assert [(row['kind'], row['status']) for row in entries(server)] == [(kind, 'running')]
    server.activity_coordinator.finish(conn, activity_id, True)
    assert [(row['kind'], row['status']) for row in entries(server)] == [(kind, 'success')]


def test_declarative_bindings_keep_remote_file_and_job_services_history_free(setup_history):
    from server.application.history.activity_bindings import remote_file_bindings, job_bindings
    server, conn = setup_history
    adapter = server.command_adapter

    class RemoteFiles:
        def delete_paths(self, client_id, paths, origin='web_api'):
            entry_id = adapter.scoped_entry(conn)
            adapter.dispatch(conn, entry_id, f'delete {paths[0]}', 'command')
            return {'message': 'deleted'}

        def list_directory(self, client_id):
            return {'items': []}

    class Jobs:
        def start_job(self, client_id, job_name, params=None, execution_mode='inproc', origin='web_api'):
            entry_id = adapter.scoped_entry(conn)
            adapter.dispatch(conn, entry_id, '', 'control', payload={'job_name':'check'}, domain='job', action='start')
            return {'job_id': 'job-1', 'message': 'started'}

    remote = adapter.instrument(RemoteFiles(), remote_file_bindings())
    assert remote.list_directory('client-1') == {'items': []}
    assert not entries(server)
    assert remote.delete_paths('client-1', ['/tmp/test'])['message'] == 'deleted'
    assert entries(server)[0]['kind'] == 'remote_files'

    jobs = adapter.instrument(Jobs(), job_bindings())
    jobs.start_job('client-1', 'check')
    assert {(row['kind'], row['status']) for row in entries(server)} == {
        ('remote_files', 'success'), ('background_job', 'success'),
    }


def test_external_tool_exec_and_cli_job_result_stay_inside_command_adapter(setup_history):
    from core.protocol.structured_arg_codec import encode_structured_arg
    from server.application.history.activity_definitions import ActivityOperation
    import json
    server, conn = setup_history
    adapter = server.command_adapter
    coordinator = server.activity_coordinator
    activity_id = coordinator.prepare(conn, ActivityOperation('command', 'invoke', {}, text='xt exec ffmpeg -version'))
    adapter.dispatch(conn, activity_id, 'external_tool_exec ' + encode_structured_arg({
        'exec_name': 'ffmpeg', 'package_id': 'ffmpeg',
    }), 'command')
    row = entries(server)[0]
    assert row['kind'] == 'external_tool'
    assert row['invocation']['arguments'] == {'exec_name': 'ffmpeg', 'package_id': 'ffmpeg'}

    job_id = coordinator.prepare(conn, ActivityOperation('command', 'invoke', {}, text='job stop check'))
    cmd = {'job_key': 'check'}
    adapter.dispatch(conn, job_id, '', 'control', payload=cmd, domain='job', action='stop')
    from core.protocol.job_control import build_job_control_result
    result = build_job_control_result('stop', 'stopped', job_id='job-1')
    assert list(adapter.observe_result(conn, job_id, 'control', '', [(1, result)], payload=cmd, domain='job', action='stop')) == [(1, result)]
    row = next(row for row in entries(server) if row['kind'] == 'background_job')
    assert row['resolved'].get('job_id') == 'job-1'
    assert row['invocation']['input'] == 'job stop check'


def test_transfer_adapters_track_both_wire_transports_and_not_browser_staging(setup_history):
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
    server.lifecycle_adapter.transfer_command_dispatched(conn, 'transfer-2')
    assert len(entries(server)) == 2
    transfer['state'] = 'failed'
    server.lifecycle_adapter.transfer_updated(transfer)
    assert sorted(row['status'] for row in entries(server)) == ['error', 'success']


def test_history_failures_do_not_block_declarative_business_dispatch(setup_history):
    from server.application.history.activity_bindings import process_bindings
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
    server.activity_coordinator.dispatch(conn, activity_id)
    facade = server.lifecycle_adapter.instrument_artifacts(
        Artifacts(), server.get_target_connection_by_client_id,
    )
    result = facade.register_command_output_artifact(client_id='client-1', source_command_id=42)
    assert result['artifact_id'] == 'file-1'
    assert entries(server)[0]['files'][0]['artifact_id'] == 'file-1'


def test_legacy_receive_file_claims_terminal_activity_once(setup_history):
    """A receive_file RPC is a Transfer, not a Command plus a second Transfer."""
    from core.protocol.structured_arg_codec import encode_structured_arg

    server, conn = setup_history
    command = 'receive_file ' + encode_structured_arg({'transfer_id': 'upload-legacy'})
    candidate = server.command_adapter.prepare_command(conn, 'upload report.pdf', source='cli')
    transfer = {
        'transfer_id': 'upload-legacy', 'client_id': 'client-1',
        'direction': 'server_to_client', 'filename': 'report.pdf',
        'destination_path': '/tmp', 'total_bytes': 10, 'state': 'running',
        'metadata': {'source': 'cli', 'history_entry_id': candidate},
    }
    server.lifecycle_adapter.bind_transfer_service(SimpleNamespace(
        get_transfer=lambda transfer_id: transfer if transfer_id == 'upload-legacy' else None,
    ))
    server.command_adapter.bind_lifecycle_adapter(server.lifecycle_adapter)
    server.command_adapter.dispatch(conn, candidate, command, 'command')
    rows = entries(server)
    assert len(rows) == 1
    assert rows[0]['activity_id'] == candidate
    assert (rows[0]['kind'], rows[0]['action'], rows[0]['status']) == ('transfer', 'upload_files', 'running')
    assert rows[0]['invocation']['input'] == 'upload report.pdf'

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
    adapter.dispatch(conn, activity_id, 'external_tool_status payload', 'command')
    adapter.dispatch(conn, activity_id, 'external_tool_instance_read payload', 'command')
    assert entries(server) == []
    adapter.dispatch(conn, activity_id, wire + ' payload', 'command')
    rows = entries(server)
    assert len(rows) == 1
    assert (rows[0]['kind'], rows[0]['action'], rows[0]['status']) == (
        'external_tool', expected_action, 'running')
    assert rows[0]['invocation']['input'] == command
    assert 'payload' not in str(rows[0]['invocation'])

    # Restart/create --start may send a second mutating Client command: one activity only.
    adapter.dispatch(conn, activity_id, 'external_tool_start payload', 'command')
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
    adapter.dispatch(conn, activity_id, 'external_tool_status payload', 'command')
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
    server.command_adapter.dispatch(conn, activity_id, 'external_tool_clear_package_cache payload', 'command')
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
    adapter.dispatch(conn, activity_id, client_command, 'command')
    assert [(row['kind'], row['action']) for row in entries(server)] == [
        ('external_tool', 'run_exec')
    ]
    assert entries(server)[0]['invocation']['input'] == 'xt exec ffmpeg -version'
