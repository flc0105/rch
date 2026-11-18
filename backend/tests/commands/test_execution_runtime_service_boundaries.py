"""Direct Runtime service dependencies after retiring PythonProcessExecutionMixin."""

import subprocess
from types import SimpleNamespace

import pytest

from client.commands.runtime.executor import CommandExecutor
from client.commands.shell.common.execution import ShellExecutionCommands
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError, ExecutionContext
from client.runtime.execution.python_execution.service import PythonExecutionService
from client.runtime.execution.scope import ExecutionScope
from client.scripts.manager import ScriptExecution
from core.protocol.script_execution import ExecutionMode, OutputMode, ScriptRunModes


def test_shell_and_script_no_longer_inherit_python_process_mixin():
    assert not any(base.__name__ == 'PythonProcessExecutionMixin' for base in ShellExecutionCommands.__bases__)
    assert not any(base.__name__ == 'PythonProcessExecutionMixin' for base in ScriptExecution.__bases__)


def test_python_service_cached_per_scope_and_process_service_shared():
    scope = ExecutionScope(SimpleNamespace(client_id='client'), ExecutionContext(101))
    assert scope.python_execution_service is scope.python_execution_service
    assert scope.process_execution_service is scope.process_execution_service
    assert scope.python_execution_service.owner is scope
    assert scope.process_execution_service.owner is scope


def test_python_context_and_collect_stream_share_strategy(monkeypatch):
    events, built = [], []

    class Strategy:
        def execute_collect(self, code, kwargs, timeout):
            events.append(('collect', code, kwargs, timeout))
            return 1, 'collect'

        def execute_stream(self, code, kwargs, timeout):
            events.append(('stream', code, kwargs, timeout))
            return 1, 'stream'

    def create(owner, **kwargs):
        built.append((owner, kwargs))
        return Strategy()

    monkeypatch.setattr('client.runtime.execution.python_execution.service.build_python_execution_strategy', create)
    owner = SimpleNamespace(socket=SimpleNamespace(client_id='my-client', client_session_token='token'), command_id=54)
    service = PythonExecutionService(owner)
    assert service.execute('x=1', kwargs={'foo': 3}, script_name='test.py', timeout=8) == (1, 'collect')
    assert service.execute('x=2', kwargs={'bar': 4}, stream=True, timeout=9) == (1, 'stream')
    assert len(built) == 1
    _, command, params, timeout = events[0]
    assert (command, timeout) == ('x=1', 8)
    assert params['foo'] == 3
    assert params['__context__']['client_id'] == 'my-client'
    assert params['__context__']['command_id'] == 54
    assert params['__context__']['client_session_token'] == 'token'
    assert params['__context__']['script_name'] == 'test.py'
    assert 'script_name' not in events[1][2]['__context__']


def test_shell_invocation_uses_shared_python_service():
    socket = SimpleNamespace(send_event=lambda *args, **kwargs: None, client_id='c1')
    executor = CommandExecutor(socket)
    assert executor.execute_command(151, 'pyexec print(456)') == (1, '456\n')
    host = executor.get_commands()
    assert host.python_execution_service.owner is host
    assert host.process_execution_service.owner is host


def test_script_inproc_uses_same_python_service_without_shell_host():
    scope = ScriptExecution(SimpleNamespace(send_event=lambda *a: None, client_id='abc'), ExecutionContext(152))
    result = scope.run_script('print("script shared")', {}, 'shared.py',
                              modes=ScriptRunModes(ExecutionMode.INPROC, OutputMode.COLLECT))
    assert result == (1, 'script shared\n')
    assert scope.python_execution_service.owner is scope


def test_spawn_short_commands_check_before_side_effect(monkeypatch):
    executor = CommandExecutor(SimpleNamespace())
    host = executor.get_commands()
    monkeypatch.setattr(host, '_checkpoint', lambda **kw: (_ for _ in ()).throw(CommandCancelledError('stop')))
    assert host.bgrun('echo never') == (0, 'Command cancelled')
    assert host.run_detached('not-a-real-executable') == (0, 'Command cancelled')
    assert host.cd('.') == (0, 'Command cancelled')


def test_timeout_text_consistent_across_command_boundaries(monkeypatch):
    executor = CommandExecutor(SimpleNamespace())
    host = executor.get_commands()
    def timeout(**kw):
        raise CommandTimeoutError('expired')
    monkeypatch.setattr(host, '_checkpoint', timeout)
    assert host.cd('.') == (0, 'Command timed out')
    assert host.bgrun('echo never') == (0, 'Command timed out')
    assert host.run_detached('never') == (0, 'Command timed out')


def test_python_interruption_preserves_partial_output(monkeypatch):
    executor = CommandExecutor(SimpleNamespace())
    host = executor.get_commands()
    interruption = subprocess.TimeoutExpired('python', 1)
    interruption.output = 'partial\n'
    monkeypatch.setattr(host.python_execution_service, 'execute', lambda *a, **k: (_ for _ in ()).throw(interruption))
    assert host.pyexec('print(1)') == (0, 'partial\n\nCommand timed out')
    assert host.pyexec_stream('print(1)') == (0, 'partial\n\nCommand timed out')
