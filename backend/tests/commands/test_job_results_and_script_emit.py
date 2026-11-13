"""Typed Job result and Script event presentation across request boundaries."""
import json
from types import SimpleNamespace

import pytest

from client.runtime.control_dispatcher import ClientControlDispatcher
from client.control_registration import register_control_domain
from client.runtime.execution.runtime import ExecutionRuntime
from client.scripts.manager import ScriptManager
from core.protocol.control import ControlDomain, JobAction, ScriptAction
from core.protocol.job_control import build_job_control_result, validate_job_control_result
from core.utils.command_output import ResultDisplay, render_result_payload
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.command.job_builtin_support import JobBuiltinSupport


def test_structured_status_text_and_json_share_identical_fields():
    data = {'job_name': 'test/probe', 'status': 'running', 'job_id': 'abc-123',
            'worker_name': 'worker', 'execution_mode': 'inproc', 'is_alive': True}
    result = build_job_control_result(JobAction.STATUS, 'Job status retrieved.', data=data,
                                      display=ResultDisplay.DATA)
    validate_job_control_result(result, JobAction.STATUS)
    text = render_result_payload(result)
    assert all(str(field) in text for field in data)
    assert json.loads(render_result_payload(result, 'json')) == data
    assert 'job_id' not in result['message']


def test_job_table_has_same_columns_in_text_and_json():
    rows = [{'job_name': 'demo', 'job_id': 'id-1', 'execution_mode': 'inproc',
             'worker_name': 'thread-1', 'status': 'running'}]
    result = build_job_control_result(JobAction.PS, '1 running Job.', data=rows,
                                      display=ResultDisplay.DATA)
    assert all(key in render_result_payload(result) for key in rows[0])
    assert json.loads(render_result_payload(result, 'json')) == rows


def test_cli_json_is_single_document_even_when_client_emits_progress():
    data = {'job_name': 'demo', 'job_id': 'id-1', 'execution_mode': 'subprocess', 'worker_name': 'worker-1'}
    result = build_job_control_result(JobAction.START, 'Job demo started (subprocess).',
                                      data=data, job_ids=['id-1'])
    class Remote:
        def stream_command(self, conn, command, **kwargs):
            yield (1, 'Downloading Job from Server: demo')
            yield (1, 'Job saved locally: /tmp/job/remote_job.py')
            yield (1, result)
    support = JobBuiltinSupport(None, SimpleNamespace(), Remote(), None, None)
    text = list(support._send(JobAction.START, job_name='demo', params={}, execution_mode='subprocess'))
    assert len(text) == 3
    assert text[-1][1] == result['message']
    json_output = list(support._send(JobAction.START, output_format='json',
                                     job_name='demo', params={}, execution_mode='subprocess'))
    assert len(json_output) == 1
    assert json.loads(json_output[0][1]) == data
    assert 'worker-1' not in text[-1][1]


def test_completed_query_uses_same_renderer_in_common_pipeline():
    data = {'job_name': 'demo', 'status': 'running', 'job_id': 'id-1'}
    chunk = {'event_type': 'chunk', 'display': 'data', 'data': data, 'shape': 'dict', 'width': 20}
    event = CommandExecutionPipeline.build_output_event(1, chunk)
    assert json.loads(event.text) == data
    old = CommandExecutionPipeline.build_output_event(1, {'text': 'unchanged'})
    assert old.text == "{'text': 'unchanged'}"
    # Old non-typed dictionary events retain their existing text fallback.
    other = CommandExecutionPipeline.build_output_event(1, {'event_type': 'chunk', 'text': 'legacy'})
    assert other.text == 'legacy'


def _script_harness():
    frames = []
    sock = SimpleNamespace(client_id='emit-test', client_session_token='',
                           send_result=lambda *args: frames.append(args))
    runtime = ExecutionRuntime(sock)
    dispatcher = ClientControlDispatcher(runtime)
    manager = ScriptManager()
    register_control_domain(dispatcher, ControlDomain.SCRIPT, manager.execute,
                            cancel_policies={ScriptAction.RUN: manager.cancel_policy})
    return dispatcher, runtime, frames


@pytest.mark.parametrize('execution_mode', ['inproc', 'subprocess_pipe'])
@pytest.mark.parametrize('output_mode', ['stream', 'collect'])
def test_sdk_emits_ordered_text_json_text(execution_mode, output_mode):
    dispatcher, runtime, frames = _script_harness()
    source = ("from client.runtime.sdk import context\n"
              "print('before', flush=True)\n"
              "context.emit({'number': 2, 'enabled': True})\n"
              "print('after', flush=True)\n")
    request = {'script_name': 'test/misc/structured_output_probe', 'source': source,
               'params': {}, 'execution_mode': execution_mode, 'output_mode': output_mode}
    status, result = dispatcher.execute(8, 'script', 'run', request)
    assert status == 1, result
    assert result == 'Code execution completed'
    events = [frame[2] for frame in frames]
    assert len(events) == 3, events
    assert events[0].strip() == 'before'
    assert events[1] == {'event_type': 'chunk', 'display': 'data',
                         'data': {'number': 2, 'enabled': True}}
    assert events[2].strip() == 'after'
    assert all(frame[3] == 0 for frame in frames)
    assert runtime.context_store.get_existing(8) is None


@pytest.mark.parametrize('execution_mode', ['inproc', 'subprocess_pipe'])
@pytest.mark.parametrize('output_mode', ['stream', 'collect'])
def test_sdk_rejects_non_json_payload(execution_mode, output_mode):
    dispatcher, _, _ = _script_harness()
    source = "from client.runtime.sdk import context\ncontext.emit({'invalid': object()})"
    result = dispatcher.execute(9, 'script', 'run', {
        'script_name': 'test/misc/bad_output', 'source': source,
        'params': {}, 'execution_mode': execution_mode, 'output_mode': output_mode})
    assert result[0] == 0


def test_script_emit_requires_context_and_structured_input():
    from client.runtime.sdk import context
    with pytest.raises(TypeError, match='JSON object or array'):
        context.emit('not structured')
    with pytest.raises(RuntimeError, match='active Script output channel'):
        context.emit({'valid': True})


def test_general_structured_json_arrays_do_not_lose_fields():
    data = [{'name': 'a'}, {'name': 'b', 'extra': 2}]
    payload = {'event_type': 'chunk', 'display': ResultDisplay.DATA, 'data': data}
    assert json.loads(render_result_payload(payload, 'text')) == data
    for values in ([1, 2], [True, 'hello'], [None], [[1, 2]]):
        item = {'event_type': 'chunk', 'display': ResultDisplay.DATA, 'data': values}
        assert json.loads(render_result_payload(item, 'text')) == values
    assert json.loads(render_result_payload(payload, 'json')) == data
