"""v1.108 optional progress levels: typed wire, text projection, Script modes."""
import pytest
from types import SimpleNamespace

from client.control_registration import register_control_domain
from client.runtime.control_dispatcher import ClientControlDispatcher
from client.runtime.execution.runtime import ExecutionRuntime
from client.runtime.execution.scope import ExecutionResultMixin
from client.scripts.manager import ScriptManager
from core.protocol.control import ControlDomain, ScriptAction
from core.protocol.result_envelope import build_result_wire_event, result_wire_event
from core.utils.output_marker import render_result_message
from server.application.command.command_execution_pipeline import CommandExecutionPipeline


@pytest.mark.parametrize('level,marker', [
    ('info', '[*]'), ('success', '[+]'), ('warning', '[!]'), ('error', '[-]'),
])
def test_levelled_progress_is_a_single_server_presentation(level, marker):
    result = build_result_wire_event(123, {
        'event_type': 'progress', 'level': level, 'message': 'stage done',
    })
    assert result['type'] == 'result' and result['id'] == 123
    assert result['level'] == level
    assert result['message'] == 'stage done'  # raw fact, no text marker
    assert render_result_message(result) == f'{marker} stage done'
    assert CommandExecutionPipeline.build_output_event(1, result).text == f'{marker} stage done'
    assert render_result_message({**result, 'message': f'{marker} stage done'}) == f'{marker} stage done'


def test_unlevelled_progress_and_stdout_chunks_have_no_markers():
    for event in [
        {'event_type': 'progress', 'message': 'ready'},
        {'event_type': 'chunk', 'message': '[*] user-generated'},
        {'event_type': 'chunk', 'message': 'netstat output'},
    ]:
        wire = build_result_wire_event(1, event)
        assert 'level' not in wire
        assert render_result_message(wire) == event['message']
    assert result_wire_event(77, 1, 'done')['status'] == 'success'


@pytest.mark.parametrize('event', [
    {'event_type': 'chunk', 'message': 'hi', 'level': 'success'},
    {'event_type': 'completed', 'message': '', 'status': 'success', 'level': 'info'},
    {'event_type': 'progress', 'message': 'hi', 'level': 'bogus'},
    {'event_type': 'progress', 'message': 'hi', 'status': 'error'},
])
def test_bad_level_or_intermediate_status_is_rejected(event):
    with pytest.raises(ValueError):
        build_result_wire_event(1, event)


def test_scope_uses_only_typed_events_not_numeric_eof():
    sent = []
    scope = ExecutionResultMixin()
    scope.command_id = 24
    scope.socket = SimpleNamespace(send_event=lambda ident, event: sent.append((ident, event)))
    scope.emit_progress('no marker')
    scope.emit_progress('stage success', level='success')
    scope.emit_chunk('raw stdout')
    scope.emit_chunk(data={'key': 'value'})
    scope.emit_completed(status='partial', message='1/2', data={'succeeded': 1})
    assert [event['event_type'] for _, event in sent] == [
        'progress', 'progress', 'chunk', 'chunk', 'completed',
    ]
    assert [event.get('level') for _, event in sent] == [None, 'success', None, None, None]
    assert sent[-1][1]['status'] == 'partial'
    assert all(ident == 24 for ident, _ in sent)


@pytest.mark.parametrize('mode', ['inproc', 'subprocess_pipe'])
@pytest.mark.parametrize('output', ['collect', 'stream'])
def test_script_progress_is_real_progress_across_four_modes(mode, output):
    sent = []
    socket = SimpleNamespace(client_id='v108-script', client_session_token='',
                             send_event=lambda ident, event: sent.append((ident, event)))
    runtime = ExecutionRuntime(socket)
    dispatcher = ClientControlDispatcher(runtime)
    manager = ScriptManager()
    register_control_domain(dispatcher, ControlDomain.SCRIPT, manager.execute,
                            cancel_policies={ScriptAction.RUN: manager.cancel_policy})
    code = ("from client.runtime.sdk import context\n"
            "context.progress('without level')\n"
            "context.progress('step good', level='success')\n"
            "context.progress('step failed', level='error')\n"
            "print('plain stdout', flush=True)\n"
            "context.emit({'item': 1})\n")
    status, result = dispatcher.execute(8, 'script', 'run', {
        'script_name': 'test/misc/progress_level_probe', 'source': code,
        'params': {}, 'execution_mode': mode, 'output_mode': output,
    })
    assert status == 1, result
    events = [event for _, event in sent]
    progress = [event for event in events if event['event_type'] == 'progress']
    assert [(event['message'], event.get('level')) for event in progress] == [
        ('without level', None), ('step good', 'success'), ('step failed', 'error'),
    ]
    assert any(event.get('data') == {'item': 1} for event in events)
    if output == 'stream':
        assert any(event.get('message') == 'plain stdout' for event in events)
    else:
        assert ('plain stdout' in str(result) or
                any(event.get('message') == 'plain stdout' for event in events))
    assert all('status' not in event for event in events)  # active progress != terminal status

@pytest.mark.parametrize('transfer_id', ['', 'independent-transfer-id'])
def test_http_download_does_not_duplicate_independent_transfer_progress(tmp_path, transfer_id):
    from client.runtime.http_transfer.http_file_transfer_service import HttpFileTransferService
    target = tmp_path / 'download.bin'
    stages, updates = [], []

    class Strategy:
        def download_file(self, url, path, progress_callback=None):
            assert url == 'https://example.invalid/file'
            with open(path, 'wb') as fp:
                fp.write(b'RCH')
            return 'ok'

    owner = SimpleNamespace(emit_progress=lambda message, *, level=None: stages.append((level, message)))
    client_api = SimpleNamespace(normalize_file_transfer_url=lambda url: url)
    service = HttpFileTransferService(owner, client_api=client_api)
    service.get_transfer_strategy = lambda: Strategy()
    service._send_transfer_update = lambda *args, **kwargs: updates.append((args, kwargs))
    service._build_progress_callback = lambda *args: lambda *_: None
    assert service.download_file_from_http('https://example.invalid/file', str(target),
                                          transfer_id=transfer_id) == 'ok'
    assert target.read_bytes() == b'RCH'
    if transfer_id:
        assert stages == []
        assert [entry[1]['stage'] for entry in updates] == ['transferring', 'completed']
    else:
        assert stages == [('info', 'Downloading: download.bin'),
                          ('success', 'Download completed: download.bin')]
        assert updates == []


def test_http_upload_prep_is_not_duplicated_for_independent_transfer(tmp_path):
    from client.runtime.http_transfer.http_file_transfer_service import HttpFileTransferService
    file_path = tmp_path / 'payload.txt'
    file_path.write_text('abc')
    stages, updates = [], []

    class FakeResponse:
        def raise_for_status(self):
            pass

    class FakeStrategy:
        def get_mode_name(self):
            return 'legacy'
        def get_buffer_size(self):
            return 4096
        def upload_file(self, *args, **kwargs):
            return FakeResponse()

    owner = SimpleNamespace(socket=SimpleNamespace(client_id='test'), command_id=1,
                            emit_progress=lambda message, *, level=None: stages.append((level, message)))
    api = SimpleNamespace(build_file_upload_url=lambda: 'https://example.invalid/upload',
                          try_parse_json=lambda response: {'data': {'original_name': 'payload.txt'}})
    service = HttpFileTransferService(owner, client_api=api)
    service.get_transfer_strategy = lambda: FakeStrategy()
    service._send_transfer_update = lambda *args, **kwargs: updates.append((args, kwargs))
    service._build_progress_callback = lambda *args: lambda *_: None
    status, message = service.upload_single_file_to_server_result(str(file_path), transfer_id='transfer-1')
    assert status == 1 and message == 'Upload completed: payload.txt'
    assert stages == []
    assert [entry[1]['stage'] for entry in updates] == ['preparing', 'staging', 'finalizing', 'completed']


def test_server_inbound_keeps_progress_level_but_rejects_level_on_chunk():
    from server.connection.services.message_router import ServerInboundMessageRouter
    received = []
    connection = SimpleNamespace(
        services=SimpleNamespace(result_dispatcher=SimpleNamespace(
            dispatch_result=lambda ident, packet, before_enqueue=None:
                (before_enqueue(), received.append((ident, packet)), True)[-1])),
        update_current_workdir=lambda cwd: None,
        context=SimpleNamespace(on_client_message_received=lambda *_: None),
    )
    router = ServerInboundMessageRouter(connection)
    packet = build_result_wire_event(19, {
        'event_type': 'progress', 'level': 'warning', 'message': 'One item skipped',
    })
    router.handle_result_message(packet)
    assert received == [(19, packet)]
    router.handle_result_message({**packet, 'event_type': 'chunk'})
    assert len(received) == 1


def test_activity_raw_result_keeps_clean_message_and_visible_output_gets_marker():
    pytest.importorskip('werkzeug.security', reason='Activity service requires full Server dependencies')
    from core.protocol.message_queue import ResultChunk
    from server.application.history.command_dispatch_adapter import CommandDispatchAdapter

    class Coordinator:
        def __init__(self):
            self.raw = []
            self.visible = []
        def own_request_output(self, *args):
            pass
        def append_result_event(self, _, __, event):
            self.raw.append(dict(event))
        def append_request_output(self, _, __, status, message, eof):
            self.visible.append(message)
        def finish(self, *args, **kwargs):
            pass
        def add_references(self, *args, **kwargs):
            pass

    coordinator = Coordinator()
    adapter = CommandDispatchAdapter(coordinator, lambda *_: None)
    wire = build_result_wire_event(77, {
        'event_type': 'progress', 'level': 'error', 'message': 'Retry failed',
    })
    completion = build_result_wire_event(77, {
        'event_type': 'completed', 'status': 'success', 'message': 'Eventually succeeded',
    })
    rows = [ResultChunk(1, wire, False, event=wire),
            ResultChunk(1, completion, True, event=completion)]
    assert list(adapter.observe_result(SimpleNamespace(), 'activity-1',
                                       {'type': 'control'}, rows)) == rows
    assert coordinator.raw == [wire, completion]
    assert coordinator.visible == ['[-] Retry failed', 'Eventually succeeded']
