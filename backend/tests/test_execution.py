"""Foreground ownership, cancellation and terminal results."""

import os
from types import SimpleNamespace

import pytest

from client.commands.runtime.interrupts import timeout
from client.commands.shell.decorators import shell_command
from client.commands.shell.runner import ShellCommandRunner
from client.controls.dispatcher import ClientControlDispatcher
from client.controls.registration import register_control_domain
from client.runtime.execution.context import CommandCancelledError, ExecutionContext
from client.runtime.execution.context_store import ExecutionContextStore
from client.runtime.execution.runtime import ExecutionRuntime
from client.scripts.manager import ScriptManager
from core.protocol.control import ControlDomain, ScriptAction
from core.protocol.message_queue import ResultChunk
from server.application.execution.command_stream_service import CommandStreamService
from server.connection.runtime.pending_results import PendingResults
from server.connection.runtime.session_execution_runtime import SessionExecutionRuntime
from server.connection.runtime.session_runtime import ClientSessionRuntime


def test_server_timeout_option_and_method_budget_take_stricter_deadline():
    store = ExecutionContextStore()
    assert store.extract_timeout({'timeout': 5}) == 5
    assert store.extract_timeout({'_timeout': 7}) == 7
    ctx = store.get_or_create(1, timeout=5)
    command = SimpleNamespace(execution_context=ctx, _checkpoint=lambda: None)
    @shell_command('Limited')
    @timeout(30)
    def limited(self):
        return 1, 'ran'
    ShellCommandRunner(SimpleNamespace())._apply_command_policy(command, limited)
    assert ctx.timeout == 5
    @timeout(2)
    def strict(self):
        return True
    ShellCommandRunner(SimpleNamespace())._apply_command_policy(command, strict)
    assert ctx.timeout == 2


def test_cancel_ack_is_not_same_as_actual_stopped():
    ctx = ExecutionContext(3)
    ctx.set_cancel_policy('cooperative')
    events = []
    ctx.on_completion(events.append)
    reply = ctx.request_cancel()
    assert reply['accepted'] and reply['state'] == 'accepted'
    assert events == []
    with pytest.raises(CommandCancelledError):
        ctx.raise_if_interrupted()
    ctx.finish()
    assert events == ['stopped']


def test_accepted_cancel_but_command_completes_normally():
    ctx = ExecutionContext(4)
    ctx.set_cancel_policy('cooperative')
    states = []
    ctx.on_completion(states.append)
    assert ctx.request_cancel()['state'] == 'accepted'
    ctx.finish()
    assert states == ['completed']


def test_foreground_listener_emits_only_actual_transitions_in_order():
    state = SessionExecutionRuntime()
    observed = []
    state.set_foreground_task_listener(lambda: observed.append(state.get_foreground_task()))
    state.acquire_foreground_task('command', 'shell sleep 10', task_id='t', web_task=True)
    state.bind_foreground_command_id(8)
    state.bind_foreground_command_id(8)  # unchanged: no new event
    state.request_foreground_task_cancel('t')
    state.request_foreground_task_cancel('t')
    state.record_cancel_ack(8, 'accepted')
    state.record_cancel_ack(999, 'completed')
    state.record_cancel_ack(8, 'stopped')
    state.record_cancel_ack(8, 'accepted')
    state.release_foreground_task('t')
    state.release_foreground_task('t')
    assert [item['cancel_state'] if item else 'Idle' for item in observed] == [
        'running', 'running', 'requested', 'accepted', 'stopped', 'Idle'
    ]
    assert observed[0]['command_id'] is None
    assert observed[1]['command_id'] == 8


def packet(request_id, phase, *, status=None, message=None, data=None):
    result = {'type': 'result', 'id': request_id, 'event_type': phase}
    if status is not None:
        result['status'] = status
    if message is not None:
        result['message'] = message
    if data is not None:
        result['data'] = data
    return result


def rows(*items):
    for event, legacy_status in items:
        yield ResultChunk(legacy_status, event, event['event_type'] == 'completed',
                          terminal_authoritative=True, event=event)


def test_pending_queue_is_event_native_and_rejects_duplicate_terminal():
    pending = PendingResults()
    result_queue = pending.register(13)
    progress = packet(13, 'progress', message='waiting')
    done = packet(13, 'completed', status='partial', data={'ok': 2, 'failed': 1})
    assert pending.deliver(13, progress)
    assert pending.deliver(13, done)
    assert not pending.deliver(13, packet(13, 'completed', status='success'))
    assert result_queue.get(False) is progress
    assert result_queue.get(False) is done
    assert result_queue.empty()


def test_pending_disconnect_inserts_authoritative_interrupted_completion():
    runtime = ClientSessionRuntime()
    events = runtime.pending_results.register(99)
    runtime.pending_results.deliver(99, packet(99, 'chunk', message='half'))
    runtime.pending_results.close()
    conn = SimpleNamespace(context=SimpleNamespace(), send_cancel=lambda *_: None)
    result = list(runtime.wait_for_result(conn, 99, 'test', results=events))
    assert len(result) == 2
    assert result[0].event['event_type'] == 'chunk'
    assert result[-1].event['event_type'] == 'completed'
    assert result[-1].event['status'] == 'interrupted'
    assert result[-1][0] == 0 and result[-1].eof


def test_invalid_structured_data_and_missing_completion_do_not_succeed():
    with pytest.raises(RuntimeError, match='expected object'):
        CommandStreamService.json_payload(CommandStreamService.collect_envelope(rows(
            (packet(7, 'completed', status='success', data=[1, 2]), 1),
        )), command_type='control')
    with pytest.raises(RuntimeError, match='without completed'):
        CommandStreamService.collect_envelope(rows(
            (packet(7, 'chunk', message='still working'), 1),
        ))
    with pytest.raises(RuntimeError, match='Duplicate completed'):
        CommandStreamService.collect_envelope(rows(
            (packet(7, 'completed', status='success'), 1),
            (packet(7, 'completed', status='error'), 0),
        ))


def harness():
    frames = []
    sock = SimpleNamespace(client_id='mode-test', client_session_token='', send_result=lambda *args: frames.append(args),
                           send_event=lambda request_id, event: frames.append(event))
    execution = ExecutionRuntime(sock)
    manager = ScriptManager()
    dispatcher = ClientControlDispatcher(execution)
    register_control_domain(dispatcher, ControlDomain.SCRIPT, manager.execute, cancel_policies={ScriptAction.RUN: manager.cancel_policy})
    return dispatcher, execution, frames


def payload(code, execution, output):
    return {'script_name':'test/probe','source':code,'params':{},'execution_mode':execution,'output_mode':output}


@pytest.mark.parametrize('mode', ['inproc', 'subprocess_pipe'])
@pytest.mark.parametrize('output', ['collect', 'stream'])
def test_script_execution_preserves_output_and_releases_context(mode, output):
    dispatch, runtime, frames = harness()
    source = 'import os, sys\nprint(os.getpid())\nprint("中文")\nprint()\nprint("warning",file=sys.stderr)\nprint("tail",end="")'
    status, result = dispatch.execute(1, 'script', 'run', payload(source, mode, output))
    assert status == 1
    if output == 'collect':
        assert not frames
        lines = result.splitlines()
    else:
        assert all(frame['event_type'] == 'chunk' for frame in frames)
        lines = [frame['message'] for frame in frames]
    assert (int(lines[0]) == os.getpid()) == (mode == 'inproc')
    assert lines[1:] == ['中文', '', 'warning', 'tail']
    assert runtime.context_store.get_existing(1) is None
