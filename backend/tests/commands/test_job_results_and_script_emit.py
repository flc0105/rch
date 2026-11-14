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
    assert json.loads(json_output[0][1]) == {'status': 'success', 'message': result['message']}
    assert 'worker-1' not in text[-1][1]


@pytest.mark.parametrize('action,payload,method', [
    (JobAction.PS, {}, 'list_running_jobs'),
    (JobAction.STATUS, {'job_key': 'demo'}, 'get_job_status'),
])
def test_live_job_queries_keep_status_internal_and_message_empty(action, payload, method):
    from client.jobs.control import JobControl
    data = ([{'job_name': 'demo', 'status': 'running'}] if action == JobAction.PS
            else {'job_name': 'demo', 'status': 'running', 'job_id': 'abc'})
    manager = SimpleNamespace(**{method: lambda *_args: data})
    status, result = JobControl.execute(manager, SimpleNamespace(), action, payload)
    assert status == 1 and result['status'] == 'success'
    assert result['message'] == '' and result['display'] == ResultDisplay.DATA
    assert json.loads(render_result_payload(result, 'json')) == data
    assert 'demo' in render_result_payload(result)


def test_empty_job_ps_is_data_result_with_json_empty_array():
    from client.jobs.control import JobControl
    manager = SimpleNamespace(list_running_jobs=lambda: [])
    status, result = JobControl.execute(manager, SimpleNamespace(), JobAction.PS, {})
    assert status == 1
    assert result['status'] == 'success'
    assert result['display'] == ResultDisplay.DATA
    assert result['data'] == []
    assert render_result_payload(result) == 'No background jobs are currently running.'
    assert json.loads(render_result_payload(result, 'json')) == []


def test_failed_data_result_uses_failure_message_not_success_table():
    failed = build_job_control_result(JobAction.STATUS, 'Job not found: missing',
                                      status='error', data={'status': 'missing'},
                                      display=ResultDisplay.DATA)
    assert render_result_payload(failed) == 'Job not found: missing'
    assert json.loads(render_result_payload(failed, 'json')) == {
        'status': 'error', 'message': 'Job not found: missing'}


def test_empty_stop_all_json_has_no_batch_counters_or_placeholder_data():
    from client.jobs.control import JobControl
    manager = SimpleNamespace(stop_all_jobs=lambda: {'stopped': [], 'errors': []})
    status, result = JobControl.execute(manager, SimpleNamespace(), JobAction.STOP_ALL, {})
    assert status == 1
    assert result['display'] == ResultDisplay.MESSAGE
    assert 'data' not in result
    assert render_result_payload(result) == 'No background jobs are currently running.'
    assert json.loads(render_result_payload(result, 'json')) == {
        'status': 'success', 'message': 'No background jobs are currently running.'}


def test_job_failure_json_keeps_status_and_message_without_duplicate_error():
    from client.jobs.control import JobControl
    scope = SimpleNamespace(_send_interim_result=lambda *_: None,
                            client_api=SimpleNamespace(download_job=lambda *_args, **_kwargs:
                                                       (_ for _ in ()).throw(FileNotFoundError('Job not found: xxxx'))))
    status, result = JobControl.execute(None, scope, JobAction.START, {
        'job_name': 'xxxx', 'execution_mode': 'subprocess', 'params': {}})
    assert status == 0
    assert render_result_payload(result) == 'Job not found: xxxx'
    assert json.loads(render_result_payload(result, 'json')) == {
        'status': 'error', 'message': 'Job not found: xxxx'}


@pytest.mark.parametrize('action,payload', [
    (JobAction.STOP, {'job_key': 'xxxx'}),
    (JobAction.PS, {}),
    (JobAction.STATUS, {'job_key': 'xxxx'}),
    (JobAction.STOP_ALL, {}),
])
def test_job_action_errors_do_not_stack_failure_prefixes(action, payload):
    from client.jobs.control import JobControl

    def fail(*_args):
        raise RuntimeError('Job not found: xxxx')

    manager = SimpleNamespace(stop_job=fail, list_running_jobs=fail,
                              get_job_status=fail, stop_all_jobs=fail)
    status, result = JobControl.execute(manager, SimpleNamespace(), action, payload)
    assert status == 0
    assert render_result_payload(result) == 'Job not found: xxxx'
    assert json.loads(render_result_payload(result, 'json')) == {
        'status': 'error', 'message': 'Job not found: xxxx'}


def test_job_error_without_exception_message_has_readable_fallback():
    from client.jobs.control import JobControl

    def fail():
        raise RuntimeError()

    status, result = JobControl.execute(SimpleNamespace(list_running_jobs=fail),
                                        SimpleNamespace(), JobAction.PS, {})
    assert status == 0
    assert render_result_payload(result) == 'Job operation failed.'


def test_stop_all_has_only_actual_targets_and_failures():
    from client.jobs.control import JobControl
    manager = SimpleNamespace(stop_all_jobs=lambda: {
        'stopped': [{'job_key': 'example_monitor', 'job_id': 'id-1'}],
        'errors': [{'job_key': 'other', 'job_id': 'id-2', 'message': 'permission denied'}]})
    status, result = JobControl.execute(manager, SimpleNamespace(), JobAction.STOP_ALL, {})
    assert status == 0
    assert result['status'] == 'error'
    assert 'example_monitor' in result['message']
    assert 'Failed to stop Job other (permission denied).' in result['message']
    assert set(result['data']) == {'stopped', 'errors'}
    assert result['data']['stopped'] == [{'job_name': 'example_monitor', 'job_id': 'id-1'}]
    assert result['data']['errors'] == [{'job_name': 'other', 'job_id': 'id-2',
                                         'message': 'permission denied'}]
    assert json.loads(render_result_payload(result, 'json')) == {
        'status': 'error', 'message': result['message']}
    assert result['references'] == [{'type': 'job', 'id': 'id-1'},
                                    {'type': 'job', 'id': 'id-2'}]


def test_sdk_data_chunk_stays_unwrapped_when_completed_results_use_envelope():
    payload = {'event_type': 'chunk', 'display': ResultDisplay.DATA,
               'data': {'count': 2}}
    assert json.loads(render_result_payload(payload, 'json')) == {'count': 2}


@pytest.mark.parametrize('action,data,message', [
    (JobAction.START, {'job_id': 'job-1', 'execution_mode': 'subprocess'},
     'Job demo started (subprocess).'),
    (JobAction.STOP, {'job_id': 'job-1'}, 'Stop requested for Job demo.'),
    (JobAction.STOP_ALL, {'stopped': [{'job_name': 'demo', 'job_id': 'job-1'}]},
     'Stop requested for: demo.'),
    (JobAction.PS, [{'job_name': 'demo', 'job_id': 'job-1', 'status': 'running'}],
     '1 running Job.'),
    (JobAction.STATUS, {'job_name': 'demo', 'status': 'running', 'job_id': 'job-1'},
     'Job status retrieved: demo.'),
])
def test_all_five_job_actions_json_use_same_completed_result_fields(action, data, message):
    display = ResultDisplay.DATA if action in (JobAction.PS, JobAction.STATUS) else ResultDisplay.MESSAGE
    result = build_job_control_result(action, message, data=data, display=display)
    class Remote:
        def stream_command(self, conn, command, **kwargs):
            yield (1, result)
    support = JobBuiltinSupport(None, SimpleNamespace(), Remote(), None, None)
    payload = ({'job_name': 'demo', 'execution_mode': 'subprocess', 'params': {}}
               if action == JobAction.START else {'job_key': 'demo'}
               if action in (JobAction.STOP, JobAction.STATUS) else {})
    output = list(support._send(action, output_format='json', **payload))
    assert len(output) == 1
    assert json.loads(output[0][1]) == (
        data if display == ResultDisplay.DATA else {'status': 'success', 'message': message})
    if display == ResultDisplay.MESSAGE:
        assert render_result_payload(result) == message
    else:
        assert all(key in render_result_payload(result) for key in
                   (data[0] if isinstance(data, list) else data))


def test_server_job_validation_failure_json_is_same_contract():
    class Service:
        def prepare_job_start(self, *_args):
            raise FileNotFoundError('Job not found: xxxx')
    support = JobBuiltinSupport(None, SimpleNamespace(), None, Service(), None)
    from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
    invocation = SERVER_COMMAND_REGISTRY.parse_invocation('job', 'start xxxx --json')
    output = list(support.execute_subcommand(invocation))
    assert len(output) == 1 and output[0][0] == 0
    assert json.loads(output[0][1]) == {'status': 'error', 'message': 'Job not found: xxxx'}


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
    assert events[0] == 'before'
    assert events[1] == {'event_type': 'chunk', 'display': 'data',
                         'data': {'number': 2, 'enabled': True}}
    assert events[2] == 'after'
    assert all(frame[3] == 0 for frame in frames)
    assert runtime.context_store.get_existing(8) is None


def test_inproc_collect_mixed_output_uses_stream_line_boundaries():
    dispatcher, _, frames = _script_harness()
    source = ("from client.runtime.sdk import context\n"
              "print('first')\n"
              "print('second')\n"
              "context.emit({'key': 'value'})\n"
              "print('last')\n")
    status, result = dispatcher.execute(10, 'script', 'run', {
        'script_name': 'test/misc/structured_output_probe', 'source': source,
        'params': {}, 'execution_mode': 'inproc', 'output_mode': 'collect'})
    assert status == 1, result
    assert [frame[2] for frame in frames] == [
        'first', 'second',
        {'event_type': 'chunk', 'display': 'data', 'data': {'key': 'value'}},
        'last',
    ]


@pytest.mark.parametrize('execution_mode', ['inproc', 'subprocess_pipe'])
def test_plain_collect_without_structured_data_preserves_newlines(execution_mode):
    dispatcher, _, frames = _script_harness()
    status, result = dispatcher.execute(11, 'script', 'run', {
        'script_name': 'test/misc/plain_text_probe',
        'source': "print('first')\nprint('second')\n",
        'params': {}, 'execution_mode': execution_mode, 'output_mode': 'collect'})
    assert status == 1, result
    assert not frames
    assert result == 'first\nsecond\n'


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
