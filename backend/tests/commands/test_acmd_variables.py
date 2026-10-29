"""ACMD resolves Client variables before typed argument validation."""
import os
from types import SimpleNamespace

import pytest

from client.commands.arguments.registry import ArgumentCommandRegistry
from client.commands.common.services.process.process_service import ProcessService
from client.commands.platform.linux import LinuxCommands
from client.commands.runtime.acmd_runner import ArgumentCommandRunner
from client.commands.runtime.command_variable_resolver import CommandVariableResolver
from client.commands.runtime.request import CommandExecutionRequest
from server.application.command.command_planner import CommandPlanner


class AcmdExecutor:
    def __init__(self, registry):
        self.command_variable_resolver = CommandVariableResolver(SimpleNamespace())
        self.registry = registry
        self.invocations = 0

    def get_argument_command_registry(self):
        self.invocations += 1
        return self.registry

    def execute_bound_request(self, request, callback):
        return callback(None)


def parsed(command):
    return CommandPlanner.__new__(CommandPlanner).parse_argument_command(command)


def test_acmd_resolves_pid_before_integer_validation(monkeypatch):
    pid = os.getpid()
    monkeypatch.setattr(ProcessService, 'list_processes', lambda self: [
        {'pid': pid, 'ppid': 1, 'name': 'python', 'username': 'demo', 'status': 'running'},
    ])
    executor = AcmdExecutor(ArgumentCommandRegistry(LinuxCommands(socket=SimpleNamespace())))
    runner = ArgumentCommandRunner(executor)
    request = CommandExecutionRequest(command_id=12)

    for command in ('acmd ps --pid ${rch:pid} --json',
                    'acmd ps --pid=${rch:pid} --json',
                    'acmd ps ${rch:pid} --json'):
        payload = parsed(command)
        status, result = runner.execute(request, payload)
        assert status == 1, result
        assert str(pid) in result
        assert '${rch:pid}' in str(payload), 'ACMD input payload must not be mutated'


def test_acmd_custom_variables_and_invalid_values(monkeypatch):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda self: [
        {'pid': 43210, 'ppid': 1, 'name': 'worker', 'username': 'demo', 'status': 'running'},
    ])
    executor = AcmdExecutor(ArgumentCommandRegistry(LinuxCommands(socket=SimpleNamespace())))
    executor.command_variable_resolver.set_var('PID', '43210')
    runner = ArgumentCommandRunner(executor)
    request = CommandExecutionRequest(command_id=4)
    status, result = runner.execute(request, parsed('acmd ps --pid ${var:PID} --json'))
    assert status == 1, result
    assert '43210' in result

    invocations_before = executor.invocations
    status, message = runner.execute(request, parsed('acmd ps --pid ${rch:missing}'))
    assert status == 0
    assert 'Failed to resolve command variable' in message
    assert executor.invocations == invocations_before

    executor.command_variable_resolver.set_var('PID', 'abc')
    status, message = runner.execute(request, parsed('acmd ps --pid ${var:PID}'))
    assert status == 0 and 'integer' in message.lower()


def test_acmd_preserves_non_string_argument_types():
    executor = AcmdExecutor(ArgumentCommandRegistry(LinuxCommands(socket=SimpleNamespace())))
    runner = ArgumentCommandRunner(executor)
    result = runner.execute(CommandExecutionRequest(command_id=5), {'name': 'ps', 'args': {'json': True, 'pid': '${rch:pid}'}})
    assert result[0] in (0, 1)
    assert 'Invalid acmd payload' not in str(result)
