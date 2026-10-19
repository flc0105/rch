"""Command policy: metadata, deadline precedence, cancel modes and real subprocess cancellation."""
import inspect
from types import SimpleNamespace

import pytest

from client.commands.runtime.context import CommandExecutionContext, CommandCancelledError, CommandTimeoutError
from client.commands.runtime.context_store import CommandExecutionContextStore
from client.commands.runtime.interrupts import timeout, cancel_policy
from client.commands.runtime.shell_command_runner import ShellCommandRunner
from server.connection.runtime.session_execution_runtime import SessionExecutionRuntime
from core.utils.decorator import desc


@pytest.mark.parametrize('outer', [True, False])
def test_decorators_are_metadata_only_in_either_order(outer):
    def operation(self, arg):
        return 1, arg
    if outer:
        operation = desc('Example')(cancel_policy('cooperative')(timeout(30)(operation)))
    else:
        operation = cancel_policy('cooperative')(timeout(30)(desc('Example')(operation)))
    assert operation.__name__ == 'operation'
    assert operation.command_cancel_mode == 'cooperative'
    assert operation.command_timeout == 30
    assert operation.help == 'Example'
    assert inspect.signature(operation) == inspect.Signature([
        inspect.Parameter('self', inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter('arg', inspect.Parameter.POSITIONAL_OR_KEYWORD),
    ])


def test_server_timeout_option_and_method_budget_take_stricter_deadline():
    store = CommandExecutionContextStore()
    assert store.extract_timeout({'timeout': 5}) == 5
    assert store.extract_timeout({'_timeout': 7}) == 7
    ctx = store.get_or_create(1, timeout=5)
    command = SimpleNamespace(execution_context=ctx, _checkpoint=lambda: None)
    @desc('Limited')
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


def test_noncooperative_commands_reject_cancellation():
    ctx = CommandExecutionContext(2)
    assert ctx.request_cancel()['state'] == 'rejected'
    assert not ctx.is_cancel_requested()


def test_cancel_ack_is_not_same_as_actual_stopped():
    ctx = CommandExecutionContext(3)
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
    ctx = CommandExecutionContext(4)
    ctx.set_cancel_policy('cooperative')
    states = []
    ctx.on_completion(states.append)
    assert ctx.request_cancel()['state'] == 'accepted'
    ctx.finish()
    assert states == ['completed']


def test_server_records_requested_accepted_stopped_without_downgrades():
    state = SessionExecutionRuntime()
    state.acquire_foreground_task('command', 'shell sleep 10', task_id='t')
    state.bind_foreground_command_id(8)
    assert state.request_foreground_task_cancel('t')['cancel_state'] == 'requested'
    state.record_cancel_ack(8, 'accepted')
    assert state.get_foreground_task()['cancel_state'] == 'accepted'
    state.record_cancel_ack(8, 'stopped')
    state.record_cancel_ack(8, 'accepted')
    assert state.get_foreground_task()['cancel_state'] == 'stopped'


def test_cancel_declaration_is_not_a_forceful_thread_abort():
    @desc('Read only')
    def ordinary(self):
        return 1, 'ok'
    ctx = CommandExecutionContext(11)
    runner = ShellCommandRunner(SimpleNamespace())
    obj = SimpleNamespace(execution_context=ctx, _checkpoint=lambda: None)
    runner._apply_command_policy(obj, ordinary)
    assert ctx.request_cancel()['state'] == 'rejected'


def test_existing_builtin_method_bodies_have_no_interruptible_wrapper():
    from client.commands.common.commands import CommonCommands
    assert not hasattr(CommonCommands.shell, '__wrapped__')
    assert CommonCommands.shell.command_cancel_mode == 'process'
    assert CommonCommands.read.command_cancel_mode == 'process'
    assert getattr(CommonCommands.kill_connection, 'requires_confirmation', False)
    assert getattr(CommonCommands.reset, 'requires_confirmation', False)


def test_real_shell_process_cancel_distinguishes_ack_from_stop():
    import os
    import shlex
    import sys
    import threading
    import time
    if os.name == 'nt':
        pytest.skip('POSIX subprocess cancellation smoke test')
    from client.commands.runtime.executor import CommandExecutor

    executor = CommandExecutor(SimpleNamespace())
    outcome = {}
    command = shlex.quote(sys.executable) + " -c 'import time; time.sleep(9)'"
    worker = threading.Thread(target=lambda: outcome.setdefault('result', executor.execute_command(105, command)))
    worker.start()
    ctx = None
    for _ in range(300):
        ctx = executor.context_store.get_existing(105)
        if ctx and ctx._cancel_handlers:
            break
        time.sleep(.01)
    assert ctx is not None and ctx._cancel_handlers
    assert executor.on_command_completion(105, lambda state: outcome.setdefault('state', state))
    response = executor.cancel_command(105)
    worker.join(3)
    assert not worker.is_alive()
    assert response['state'] == 'accepted'
    assert outcome['state'] == 'stopped'
    assert outcome['result'] == (0, 'Command cancelled')


def test_server_ack_dispatch_updates_only_matching_foreground_command():
    from server.connection.services.message_router import ServerInboundMessageRouter
    runtime = SessionExecutionRuntime()
    runtime.acquire_foreground_task('command', 'shell sleep 10', task_id='task')
    runtime.bind_foreground_command_id(123)
    runtime.request_foreground_task_cancel('task')
    router = ServerInboundMessageRouter(SimpleNamespace(runtime=runtime))
    router.dispatch({'type': 'cancel_ack', 'target_id': 999, 'state': 'stopped'})
    assert runtime.get_foreground_task()['cancel_state'] == 'requested'
    router.dispatch({'type': 'cancel_ack', 'target_id': 123, 'state': 'accepted'})
    assert runtime.get_foreground_task()['cancel_state'] == 'accepted'
    router.dispatch({'type': 'cancel_ack', 'target_id': 123, 'state': 'stopped'})
    assert runtime.get_foreground_task()['cancel_state'] == 'stopped'


@pytest.mark.parametrize('mode', ['none', 'cooperative', 'process'])
def test_cancel_mode_is_pure_metadata_and_context_policy(mode):
    @cancel_policy(mode)
    def example(self):
        return 1, 'ok'
    assert example.command_cancel_mode == mode
    assert not hasattr(example, '__wrapped__')
    ctx = CommandExecutionContext(44)
    ctx.set_cancel_policy(mode)
    assert ctx.get_cancel_policy()['mode'] == mode
    assert ctx.request_cancel()['accepted'] == (mode != 'none')


def test_invalid_cancel_mode_rejected():
    with pytest.raises(ValueError):
        cancel_policy('force')
    with pytest.raises(ValueError):
        CommandExecutionContext(45).set_cancel_policy('force')


def test_shell_and_stream_declare_process_cancellation():
    from client.commands.common.commands import CommonCommands
    assert CommonCommands.shell.command_cancel_mode == 'process'
    assert CommonCommands.read.command_cancel_mode == 'process'
    # A file operation with checkpoints is cooperative, not a managed subprocess.
    assert CommonCommands.zip_dir.command_cancel_mode == 'cooperative'
    # Detached spawn cannot be cancelled after the command returns.
    assert getattr(CommonCommands.spawn, 'command_cancel_mode', 'none') == 'none'


def test_runtime_execution_strategies_select_actual_cancel_mode():
    from client.commands.strategies.python_execution.inproc import InProcessPythonExecutionStrategy
    from client.commands.strategies.python_execution.subprocess_pipe import SubprocessPipePythonExecutionStrategy
    from client.commands.strategies.http_transfer.base import HttpTransferStrategy

    observed = []
    owner = SimpleNamespace(_set_cancel_policy=lambda **kwargs: observed.append(kwargs))
    InProcessPythonExecutionStrategy(owner).configure_context()
    SubprocessPipePythonExecutionStrategy(owner).configure_context()
    HttpTransferStrategy(owner).configure_context_for_upload()
    assert [item['mode'] for item in observed] == ['none', 'process', 'none']


def test_read_uses_managed_subprocess_cancel_not_only_checkpoints():
    import os
    import shlex
    import sys
    import threading
    import time
    if os.name == 'nt':
        pytest.skip('POSIX subprocess cancellation smoke test')
    from client.commands.runtime.executor import CommandExecutor

    socket = SimpleNamespace(send_result=lambda *args: None)
    executor = CommandExecutor(socket)
    result = {}
    command = 'read ' + shlex.quote(sys.executable) + " -c 'import time; time.sleep(9)'"
    worker = threading.Thread(target=lambda: result.setdefault('return', executor.execute_command(204, command)))
    worker.start()
    ctx = None
    for _ in range(300):
        ctx = executor.context_store.get_existing(204)
        if ctx and ctx._cancel_handlers:
            break
        time.sleep(.01)
    assert ctx is not None and ctx._cancel_handlers
    assert ctx.get_cancel_policy()['mode'] == 'process'
    assert executor.on_command_completion(204, lambda state: result.setdefault('state', state))
    answer = executor.cancel_command(204)
    worker.join(4)
    assert answer['accepted'] and answer['state'] == 'accepted'
    assert not worker.is_alive()
    assert result['state'] == 'stopped'
