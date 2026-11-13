"""Job requests and results use one typed contract across CLI, Web and Client."""
from types import SimpleNamespace

import pytest

from client.jobs.command_control import ClientJobControl
from client.connection.message_router import ClientInboundMessageRouter
from core.protocol.job_control import (
    build_job_control_request, build_job_control_result,
    validate_job_control_request, validate_job_control_result,
)
from server.connection.channel.session_command_channel import ClientSessionCommandChannel
from server.connection.services.message_router import ServerInboundMessageRouter
from server.application.jobs.background_job_service import BackgroundJobService
from server.application.command.job_builtin_support import JobBuiltinSupport


def test_job_request_is_a_json_object_not_command_text():
    channel = ClientSessionCommandChannel(SimpleNamespace())
    request = build_job_control_request('stop', job_key='sample')
    packet = channel.build_command_payload('', 'control', payload=request, domain='job', action='stop')
    assert packet == {'type': 'control', 'id': 1, 'domain': 'job', 'action': 'stop', 'payload': request}
    assert 'text' not in packet
    assert channel.build_command_payload('shell pwd') == {'type': 'command', 'id': 2, 'text': 'shell pwd'}
    with pytest.raises(ValueError, match='domain and action'):
        channel.build_command_payload('invalid', 'control')
    with pytest.raises(ValueError, match='control message'):
        channel.build_command_payload('shell pwd', payload={})


@pytest.mark.parametrize('payload', [
    '', [], {'extra': 1}, {'job_name': 'x', 'execution_mode': 'inproc', 'params': []},
    {'job_key': ''}, {'job_key': 'x'},
])
def test_job_request_rejects_malformed_payload(payload):
    with pytest.raises(ValueError):
        validate_job_control_request('start', payload)


def test_result_contract_and_input_output_separation():
    request = build_job_control_request('stop_all')
    assert validate_job_control_request('stop_all', request) == request
    result = build_job_control_result('stop_all', 'stopped 2', job_ids=['a', 'b'], total=2, succeeded=2)
    assert validate_job_control_result(result, 'stop_all') is result
    assert result['job_ids'] == ['a', 'b']
    with pytest.raises(ValueError, match='counts'):
        validate_job_control_result({**result, 'failed': 1}, 'stop_all')
    with pytest.raises(ValueError):
        validate_job_control_result({'action': 'stop', 'message': 'x'}, 'stop')
    assert validate_job_control_result(build_job_control_result('ps', 'none', jobs=[]), 'ps')['jobs'] == []


def test_client_router_passes_payload_unmodified():
    calls = []
    conn = SimpleNamespace(runtime=SimpleNamespace(command_executor=SimpleNamespace(
        execute_control_command=lambda cmd_id, domain, action, payload, options=None:
            calls.append((cmd_id, domain, action, payload, options)) or (1, build_job_control_result('stop', 'stopped'))
    )))
    request = build_job_control_request('stop', job_key='demo')
    result = ClientInboundMessageRouter(conn).handle_control_message(
        {'type': 'control', 'id': 42, 'domain': 'job', 'action': 'stop', 'payload': request})
    assert calls == [(42, 'job', 'stop', request, None)]
    assert result[0:2] == (42, 1)
    assert isinstance(result[2], dict)


def test_client_operation_returns_structured_result_for_queries_and_mutations():
    class Manager:
        def list_running_jobs(self): return ['demo']
        def get_job_status(self, key): return {'job_key': key, 'state': 'running'}
        def stop_job(self, key): return SimpleNamespace(display_name=key, job_id='job-7')
        def stop_all_jobs(self): return {'stopped': [], 'errors': [], 'total': 0}
    commands = SimpleNamespace(socket=SimpleNamespace(runtime=SimpleNamespace(job_manager=Manager())))
    for action, args in [('ps', {}), ('status', {'job_key': 'demo'}),
                         ('stop', {'job_key': 'demo'}), ('stop_all', {})]:
        status, result = ClientJobControl.execute(commands, action, build_job_control_request(action, **args))
        assert status == 1
        assert isinstance(result, dict)
        validate_job_control_result(result, action)
    assert ClientJobControl.execute(commands, 'ps', {'extra': 1})[0] == 0


def test_server_result_router_preserves_structured_data():
    observed = []
    connection = SimpleNamespace(
        update_current_workdir=lambda cwd: None,
        services=SimpleNamespace(result_dispatcher=SimpleNamespace(
            dispatch_result=lambda *args: observed.append(args))))
    result = build_job_control_result('stop', 'stopped', job_id='job-7')
    ServerInboundMessageRouter(connection).handle_result_message({
        'id': 21, 'type': 'result', 'status': 1, 'data': result, 'eof': 1})
    assert observed == [(21, 1, result, 1)]
    ServerInboundMessageRouter(connection).handle_result_message({
        'id': 22, 'type': 'result', 'status': 1, 'text': 'regular text', 'eof': 1})
    assert observed[-1] == (22, 1, 'regular text', 1)


def test_cli_and_web_share_typed_requests_and_metadata_mode():
    sent = []
    class Catalog:
        def get_job_metadata(self, name):
            assert name == 'demo'
            return {'execution_mode': 'subprocess', 'allowed': ['subprocess']}
    class Remote:
        def stream_command(self, conn, command, **kwargs):
            sent.append((command, kwargs))
            yield (1, build_job_control_result('start', 'started', job_id='id-1'))
        def stream_foreground_command(self, conn, command, **kwargs):
            sent.append((command, kwargs))
            yield (1, 'Downloading job')
            yield (1, build_job_control_result('start', 'started', job_id='id-2'))
    remote = Remote()
    service = BackgroundJobService(None, None, remote, Catalog())
    service.has_active_job = lambda *_: False
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='client-1'))
    cli = JobBuiltinSupport(SimpleNamespace(), conn, remote, service, Catalog())
    assert list(cli.execute_subcommand('start', 'demo'))[-1] == (1, 'started')
    web = service.start_job('client-1', 'demo')
    assert web['execution_mode'] == 'subprocess'
    assert web['message'] == 'Downloading job\nstarted'
    assert len(sent) == 2
    for command, kw in sent:
        assert command == ''
        assert kw['command_type'] == 'control' and kw['domain'] == 'job' and kw['action'] == 'start'
        assert kw['payload'] == {'job_name': 'demo', 'params': {}, 'execution_mode': 'subprocess'}


def test_client_start_downloads_job_and_returns_real_id(monkeypatch, tmp_path):
    import client.jobs.command_control as module
    monkeypatch.setattr(module, 'make_client_temp_dir', lambda *a, **kw: str(tmp_path))
    output = []
    runtime = SimpleNamespace(job_id='job-start-1', display_name='demo', execution_mode='subprocess',
                              worker_name='worker-1', job_key='demo')
    class Manager:
        def start_job(self, path, name, command_id, *, job_params, cleanup_path, execution_mode):
            assert name == 'demo' and command_id == 39
            assert job_params == {'x': 12} and execution_mode == 'subprocess'
            assert cleanup_path == str(tmp_path)
            assert (tmp_path / 'remote_job.py').read_text() == 'print(12)'
            return runtime
    commands = SimpleNamespace(
        command_id=39, socket=SimpleNamespace(runtime=SimpleNamespace(job_manager=Manager())),
        client_api=SimpleNamespace(download_job=lambda name, timeout: 'print(12)'),
        _send_interim_result=lambda *args: output.append(args),
    )
    status, result = ClientJobControl.execute(commands, 'start', build_job_control_request(
        'start', job_name='demo', execution_mode='subprocess', params={'x': 12}))
    assert status == 1 and result['job_id'] == 'job-start-1'
    assert len(output) == 2
    assert runtime._remote_script_name == 'demo'


def test_client_result_frame_carries_typed_data_without_encoding():
    from client.connection.server_connection import ServerConnection
    sent = []
    conn = ServerConnection.__new__(ServerConnection)
    conn.send = sent.append
    result = build_job_control_result('stop', 'Stop request sent', job_id='job-1')
    conn.send_result(19, 1, result)
    assert sent[0]['data'] is result
    assert 'text' not in sent[0]
    conn.send_result(20, 1, 'plain text')
    assert sent[1]['text'] == 'plain text' and 'data' not in sent[1]
