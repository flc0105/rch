"""v1.105: visible upload output, Clipboard data, and local Builtin result facts."""
from pathlib import Path
from types import SimpleNamespace

from client.config.runtime_config_effects import RuntimeConfigEffects
from core.protocol.result_envelope import ResultEnvelope
from core.protocol.message_queue import ResultChunk
from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.execution.upload_execution_service import UploadExecutionService


def _upload_service(tmp_path: Path, state='completed'):
    file_path = tmp_path / 'send.txt'
    file_path.write_text('example', encoding='utf-8')
    sent = []
    staged = []
    session = SimpleNamespace(session_info=SimpleNamespace(client_id='client', hostname='host'),
                              send=sent.append, get_foreground_task=lambda: {})
    artifact = SimpleNamespace(
        stage_local_file=lambda *args, **kwargs: (str(file_path), 'send.txt'),
        build_upload_temp_download_relative_url=lambda path: '/temp/send.txt',
        cleanup_upload_temp_file=staged.append,
    )
    transfer = SimpleNamespace(
        create_transfer=lambda **kwargs: {'transfer_id': 'transfer-1'},
        get_transfer=lambda transfer_id: {'state': 'running', 'stage': 'transferring'},
        wait_for_terminal=lambda transfer_id: {
            'state': state, 'destination_path': '/remote/send.txt', 'total_bytes': 7,
            'error': 'disk full' if state == 'failed' else ''},
        fail_transfer=lambda *args: None,
    )
    service = UploadExecutionService(None, SimpleNamespace(get_connection=lambda target: session),
                                    artifact, transfer)
    return service, file_path, sent, staged


def test_remote_upload_success_only_has_state_events_not_redundant_visible_lines(tmp_path):
    service, file_path, sent, cleaned = _upload_service(tmp_path)
    events = list(service.iter_upload_events('client', str(file_path), source='web'))
    assert [event.event_type for event in events] == ['started', 'progress', 'completed']
    assert not any(event.text for event in events)
    assert events[-1].ok is True
    assert [event.event_type for event in events].count('completed') == 1
    assert sent[0]['type'] == 'transfer_start'
    assert cleaned == [str(file_path)]


def test_remote_upload_error_is_visible_and_has_one_terminal_result(tmp_path):
    service, file_path, _, _ = _upload_service(tmp_path, state='failed')
    events = list(service.iter_upload_events('client', str(file_path), source='web'))
    assert [event.event_type for event in events] == ['started', 'progress', 'error', 'completed']
    assert events[-2].text == 'disk full'
    assert events[-1].ok is False


def test_process_recovery_unavailable_has_explicit_warning_not_false_restart():
    connection = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': True}),
                                 process_recovery_watchdog_manager=None, watchdog_manager=None)
    effects = RuntimeConfigEffects(connection, lambda: False)
    messages = effects.apply('PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
    assert len(messages) == 1
    assert 'manager unavailable' in messages[0]
    assert 'started' not in messages[0] and 'restarted' not in messages[0]


def test_process_recovery_actual_change_reports_effect_once(monkeypatch):
    import client.config.runtime_config as runtime_config
    original = (runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED,
                runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED)
    calls = []
    conn = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': True}),
                           process_recovery_watchdog_manager=SimpleNamespace(
                               start=lambda: calls.append('start'), stop=lambda: calls.append('stop')),
                           watchdog_manager=None)
    try:
        runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED = False
        runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED = False
        messages = RuntimeConfigEffects(conn, lambda: False).apply('PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
        assert calls == ['start']
        assert messages == ['Process Recovery Watchdog started.']
    finally:
        runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED, runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED = original


def test_builtin_result_chunk_preserves_raw_data_and_text_projection():
    payload = ResultEnvelope(data=[{'name': 'example'}]).as_payload()
    chunk = ResultChunk(1, 'NAME\nexample', True, terminal_authoritative=True, event=payload)
    event = CommandExecutionPipeline.build_result_event(chunk)
    assert event.text == 'NAME\nexample'
    assert event.payload['result_envelope'] is payload
    assert event.payload['result_terminal'] == 'success'
    assert event.event_type == CommandExecutionEvent.CHUNK


def test_web_task_server_builtin_result_has_request_id_and_is_stored_once():
    from server.application.tasks.task_runner import WebTaskRunner
    runner = object.__new__(WebTaskRunner)
    emitted, recorded, visible = [], [], []
    runner._publish_task_result = lambda context, status, text, result=None: emitted.append(result)
    runner._append_history_output = lambda context, status, text: visible.append(text)
    runner._get_runtime_command_id = lambda context: 123
    runner._get_history_entry_id = lambda context: 'activity'
    runner.activity_coordinator = SimpleNamespace(
        append_result_event=lambda _conn, _entry, result: recorded.append(result))
    context = SimpleNamespace(session=object(), task_id='task', history_entry_id='activity')
    facts = ResultEnvelope(message='Done', data={'count': 3}).as_payload()
    runner._publish_stream_chunk(context, 1, 'Done', facts)
    assert emitted == recorded == [{
        'type': 'result', 'id': 123, 'event_type': 'completed',
        'status': 'success', 'message': 'Done', 'data': {'count': 3}}]
    assert visible == ['Done']


def test_web_task_client_result_is_not_saved_twice():
    from server.application.tasks.task_runner import WebTaskRunner
    runner = object.__new__(WebTaskRunner)
    emitted, recorded = [], []
    runner._publish_task_result = lambda context, status, text, result=None: emitted.append(result)
    runner._append_history_output = lambda *args: None
    runner.activity_coordinator = SimpleNamespace(append_result_event=lambda *args: recorded.append(args))
    context = SimpleNamespace()
    wire = {'type': 'result', 'id': 4, 'event_type': 'completed',
            'status': 'success', 'message': 'done'}
    runner._publish_stream_chunk(context, 1, 'done', wire)
    assert emitted == [wire] and recorded == []
