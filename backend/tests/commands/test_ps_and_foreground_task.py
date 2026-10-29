"""ACMD process options and persistent Server foreground task snapshots."""
import json
from types import SimpleNamespace

import pytest

from client.commands.arguments.registry import ArgumentCommandRegistry
from client.commands.common.services.process.process_service import ProcessService
from client.commands.platform.linux import LinuxCommands
from client.commands.platform.mac import MacCommands
from client.commands.platform.win import WindowsCommands
from server.application.command.command_planner import CommandPlanner
from server.connection.runtime.session_execution_runtime import SessionExecutionRuntime


@pytest.mark.parametrize('platform', [LinuxCommands, MacCommands, WindowsCommands])
def test_acmd_ps_rejects_removed_details_option(monkeypatch, platform):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda self: [
        {'pid': 101, 'ppid': 1, 'name': 'python', 'username': 'demo', 'status': 'running'},
    ])
    registry = ArgumentCommandRegistry(platform(socket=SimpleNamespace()))
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command('acmd ps --details --json')
    status, output = registry.execute(payload)
    assert status == 0
    assert 'details' in output.lower()
    status, output = registry.execute(CommandPlanner.__new__(CommandPlanner).parse_argument_command('acmd ps --json'))
    assert status == 1
    assert list(json.loads(output)[0]) == ['pid', 'ppid', 'name', 'username', 'status']


def test_foreground_runtime_started_state_and_release():
    runtime = SessionExecutionRuntime()
    assert runtime.get_foreground_task() is None
    task = runtime.acquire_foreground_task('command', 'shell sleep 2', 'web', 'task-123')
    assert task['started_at'].endswith('+00:00')
    assert task['cancel_state'] == 'running'
    runtime.bind_foreground_command_id(99)
    assert runtime.get_foreground_task()['command_id'] == 99
    runtime.request_foreground_task_cancel('task-123')
    assert runtime.get_foreground_task()['cancel_requested'] is True
    runtime.release_foreground_task('task-123', 'shell sleep 2')
    assert runtime.get_foreground_task() is None
