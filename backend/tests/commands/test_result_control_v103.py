"""Result v1.103 regression: consumer-oriented payloads and independent controls."""
from threading import RLock
from types import SimpleNamespace

import pytest

from core.protocol.control import (ClipboardAction, ProcessAction, RemoteFilesAction,
                                   ControlDomain, SessionAction, ExecutionPolicy, execution_policy)
from core.protocol.result_envelope import ResultEnvelope
from client.clipboard.manager import ClipboardManager
from client.process.manager import ProcessManager
from client.remote_files.manager import RemoteFilesManager
from client.runtime.filesystem.batch_file_result import BatchFileResult
from client.session.control import SessionControl
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.artifact.remote_file_service import WebRemoteFileService


class Scope:
    def _checkpoint(self):
        return None


def test_clipboard_get_keeps_data_but_set_only_returns_message():
    manager = ClipboardManager.__new__(ClipboardManager)
    manager._operation_lock = RLock()
    manager.get_clipboard = lambda mode, checkpoint: (1, {'kind': 'text', 'text': 'hello',
        'capabilities': {'text': True, 'image': False, 'files': False}})
    manager.set_clipboard = lambda *args, **kwargs: (1, {'kind': 'text', 'capabilities': {}})
    status, reply = manager.execute(Scope(), ClipboardAction.GET, {'mode': 'content'})
    assert status == 1 and reply['data']['text'] == 'hello'
    assert set(reply) == {'event_type', 'status', 'message', 'data'}
    status, reply = manager.execute(Scope(), ClipboardAction.SET, {'kind': 'text', 'text': 'hello'})
    assert status == 1 and reply == ResultEnvelope(message='Target clipboard updated').as_payload()


def test_process_kill_returns_just_message_and_errors_are_not_empty_data():
    manager = ProcessManager()
    manager.service = SimpleNamespace(kill_process=lambda pid: None)
    assert manager.execute(Scope(), ProcessAction.KILL, {'pid': 21}) == (
        1, ResultEnvelope(message='Process 21 terminated').as_payload())
    assert manager.execute(Scope(), ProcessAction.KILL, {'pid': -1}) == (0, 'PID must be a positive integer')


def test_remote_batch_status_and_minimal_data():
    manager = RemoteFilesManager()
    for outcome, succeeded, total, expected_status in [
        ((), 2, 2, 'success'), (('bad: denied',), 1, 2, 'partial'),
        (('a: denied', 'b: denied'), 0, 2, 'error')]:
        raw = BatchFileResult(action='copy', total=total, succeeded=succeeded, errors=outcome)
        wire_status, payload = manager._batch_result(raw)
        assert wire_status == int(raw.failed == 0)
        assert payload['status'] == expected_status
        assert payload['data'] == {'succeeded': succeeded, 'failed': raw.failed}
        assert set(payload) == {'event_type', 'status', 'message', 'data'}
        if outcome:
            assert 'denied' in payload['message']
    _, delete_reply = manager._batch_result(BatchFileResult(action='delete', total=2, succeeded=1, errors=('bad: denied',)))
    assert set(delete_reply) == {'event_type', 'status', 'message'}


def test_remote_archive_data_projection_only_keeps_consumed_fields():
    manager = RemoteFilesManager()
    class Resolver:
        def require_existing_file(self, path): return str(path)
        def require_existing_directory(self, path): return str(path)
    class Archive:
        def inspect_zip(self, path):
            return {'path': path, 'name': 'a.zip', 'tree': [], 'entry_count': 0,
                    'file_count': 0, 'dir_count': 0, 'archive_size': 7,
                    'uncompressed_size': 0, 'compressed_size': 5, 'limits': {'entries': 2}}
        def read_zip_text_entry(self, path, entry):
            return {'type': 'text', 'content': 'hi', 'encoding': 'utf-8', 'entry_name': entry}
        def extract_zip_with_policy(self, path, dest, entry, policy):
            return {'extracted_to': dest + '/dir', 'file_count': 44, 'mode': 'single_root'}
    scope = SimpleNamespace(path_resolver=Resolver(), archive_service=Archive())
    status, data = manager.peek_archive(scope, {'path': '/tmp/a.zip'})
    assert status == 1 and set(data) == {'path', 'name', 'tree', 'entry_count',
        'file_count', 'dir_count', 'archive_size', 'uncompressed_size'}
    status, data = manager.read_archive_entry(scope, {'path': '/tmp/a.zip', 'entry_name': 'a'})
    assert status == 1 and data == {'type': 'text', 'content': 'hi'}
    status, result = manager.extract_archive(scope, {'path': '/tmp/a.zip', 'destination_dir': '/tmp'})
    assert status == 1 and result['data'] == {'extracted_to': '/tmp/dir'}


def test_web_remote_batch_unwraps_partial_failure_without_losing_message():
    class Remote:
        def run_foreground_control(self, *args, **kwargs):
            return 0, ResultEnvelope(status='partial', message='Deleted 1 of 2 items\nErrors:\n  /x: denied',
                data={'succeeded': 1, 'failed': 1}).as_payload()
    service = WebRemoteFileService(Remote(), None)
    with pytest.raises(RuntimeError, match='denied'):
        service.delete_paths('client', ['/tmp/a', '/tmp/x'])


def test_session_disconnect_independent_and_exits_after_report(monkeypatch):
    assert execution_policy(ControlDomain.SESSION, SessionAction.DISCONNECT) is ExecutionPolicy.INDEPENDENT
    events = []
    guard = SimpleNamespace(stop=lambda: events.append(('stop_watchdog',)))
    recovery = SimpleNamespace(stop=lambda: events.append(('stop_recovery',)))
    conn = SimpleNamespace(report_session_end=lambda *args, **kwargs: events.append(('report', args, kwargs)),
                           close=lambda: events.append(('close',)),
                           watchdog_manager=guard, process_recovery_watchdog_manager=recovery)
    def quit_now(code):
        events.append(('exit', code))
        raise SystemExit(code)
    monkeypatch.setattr('client.session.control.os._exit', quit_now)
    with pytest.raises(SystemExit):
        SessionControl(conn).execute(Scope(), SessionAction.DISCONNECT, {})
    assert [entry[0] for entry in events] == ['report', 'stop_recovery', 'stop_watchdog', 'close', 'exit']
    assert events[0][1] == ('server_requested_disconnect',)


def test_session_disconnect_cleans_up_recovery_even_on_report_error(monkeypatch):
    events = []
    def report(*args, **kwargs):
        events.append('report')
        raise OSError('socket already closed')
    conn = SimpleNamespace(
        report_session_end=report,
        watchdog_manager=SimpleNamespace(stop=lambda: events.append('stop_worker')),
        process_recovery_watchdog_manager=SimpleNamespace(stop=lambda: events.append('stop_recovery')),
        close=lambda: events.append('close'),
    )
    def fake_exit(code):
        events.append('exit')
        raise SystemExit(code)
    monkeypatch.setattr('client.session.control.os._exit', fake_exit)
    with pytest.raises(SystemExit):
        SessionControl(conn).execute(Scope(), SessionAction.DISCONNECT, {})
    assert events == ['report', 'stop_recovery', 'stop_worker', 'close', 'exit']



@pytest.mark.parametrize('command,independent', [
    ('job', True), ('job ps', True), ('job status example_monitor', True),
    ('job start example_monitor', False), ('config list', True),
    ('config set SCRIPT_DEFAULT_OUTPUT_MODE stream', False),
    ('watchdog', True), ('history run 1', False), ('script list', True),
    ('pwd', False), ('shell sleep 10', False), ('help', True),
])
def test_registered_independents_only_allow_explicit_builtin_actions(command, independent):
    assert SERVER_COMMAND_REGISTRY.is_independent_input(command) is independent


def test_web_terminal_independent_guard_is_derived_from_registry_not_command_strings():
    from server.application.tasks.task_service import WebTaskService
    service = WebTaskService.__new__(WebTaskService)
    service._submit_request = lambda request: request
    for raw in ('job', 'job ps', 'job status example_monitor', 'watchdog', 'config list'):
        request = service.submit_web_command('client-1', raw)
        assert request.use_foreground_guard is False, raw
    for raw in ('pwd', 'shell sleep 5', 'job start example_monitor',
                'config set SCRIPT_DEFAULT_OUTPUT_MODE stream'):
        request = service.submit_web_command('client-1', raw)
        assert request.use_foreground_guard is True, raw


def test_server_disconnect_uses_session_control_without_borrowing_foreground_slot():
    from server.connection.client_session import ClientSession
    requests = []
    session = SimpleNamespace(note_server_disconnect=lambda reason: requests.append(('reason', reason)),
                              send_command=lambda *args, **kwargs: requests.append((args, kwargs)))
    ClientSession.request_disconnect(session)
    assert requests[0] == ('reason', 'kill_instance')
    args, keywords = requests[1]
    assert keywords['type'] == 'control'
    assert keywords['domain'] is ControlDomain.SESSION
    assert keywords['action'] is SessionAction.DISCONNECT
    assert 'track_execution' not in keywords


def test_config_success_does_not_emit_redundant_applied_progress():
    from client.config.runtime_config_effects import RuntimeConfigEffects
    actions = []
    watcher = SimpleNamespace(start=lambda: actions.append('start'), stop=lambda: actions.append('stop'))
    conn = SimpleNamespace(process_recovery_watchdog_manager=watcher,
                           runtime=SimpleNamespace(features={'watchdog': True}), watchdog_manager=None)
    manager = RuntimeConfigEffects(conn, is_launchd_managed_client=lambda: False)
    from client.config import runtime_config
    # A running supervisor may need restart; it must not emit a duplicate success line.
    saved = (runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED,
             runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED)
    try:
        runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED = False
        runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED = False
        output = manager.apply('PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
        assert actions == ['start'] and not any('Applied:' in text for text in output)
    finally:
        (runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED,
         runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED) = saved


def test_session_disconnect_stops_recovery_if_worker_stop_raises(monkeypatch):
    events = []
    def worker_stop():
        events.append('worker_stop')
        raise RuntimeError('worker already gone')
    conn = SimpleNamespace(
        report_session_end=lambda *args, **kwargs: events.append('report'),
        watchdog_manager=SimpleNamespace(stop=worker_stop),
        process_recovery_watchdog_manager=SimpleNamespace(stop=lambda: events.append('recovery_stop')),
        close=lambda: events.append('close'),
    )
    def fake_exit(code):
        events.append('exit')
        raise SystemExit(code)
    monkeypatch.setattr('client.session.control.os._exit', fake_exit)
    with pytest.raises(SystemExit):
        SessionControl(conn).execute(Scope(), SessionAction.DISCONNECT, {})
    assert events == ['report', 'recovery_stop', 'worker_stop', 'close', 'exit']
