"""Optional ACMD process details and persistent Server foreground task snapshots."""
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
def test_acmd_ps_details_opt_in(monkeypatch, platform):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda self: [
        {'pid': 101, 'ppid': 1, 'name': 'python', 'username': 'demo', 'status': 'running'},
        {'pid': 102, 'ppid': 1, 'name': 'worker', 'username': 'demo', 'status': 'sleeping'},
    ])
    visited = []

    def details(self, pid):
        visited.append(pid)
        return {'running_time': '2h 4m 1s', 'command': 'python -m demo',
                'listening_ports': '443, 8080'}

    monkeypatch.setattr(ProcessService, 'get_acmd_process_details', details)
    registry = ArgumentCommandRegistry(platform(socket=SimpleNamespace()))
    def run(cmd):
        return registry.execute(CommandPlanner.__new__(CommandPlanner).parse_argument_command(cmd))

    status, output = run('acmd ps --json')
    assert status == 1
    assert list(json.loads(output)[0]) == ['pid', 'ppid', 'name', 'username', 'status']
    assert visited == []
    status, output = run('acmd ps --details --pid 101 --json')
    assert status == 1, output
    row, = json.loads(output)
    assert row['running_time'] == '2h 4m 1s'
    assert row['command'] == 'python -m demo'
    assert row['listening_ports'] == '443, 8080'
    assert visited == [101]


def test_acmd_process_details_multilistening_and_unavailable(monkeypatch):
    from client.commands.common.services.process import process_service

    class Conn:
        def __init__(self, status, port):
            self.status = status
            self.laddr = ('0.0.0.0', port)
    class Process:
        def __init__(self, pid):
            self.pid = pid
        def create_time(self):
            return 1000
        def cmdline(self):
            return ['/bin/daemon', '-d']
        def net_connections(self, kind):
            assert kind == 'inet'
            return [Conn('LISTEN', 5000), Conn('LISTENING', 8000), Conn('ESTABLISHED', 9000), Conn('LISTEN', 5000)]
    monkeypatch.setattr(process_service, 'psutil', SimpleNamespace(Process=Process, NoSuchProcess=LookupError,
                       AccessDenied=PermissionError, ZombieProcess=RuntimeError), raising=False)
    import sys
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=Process, NoSuchProcess=LookupError,
                          AccessDenied=PermissionError, ZombieProcess=RuntimeError))
        patch.setattr('time.time', lambda: 1000 + 61)
        info = ProcessService(None).get_acmd_process_details(111)
    assert info['listening_ports'] == '5000, 8000'
    assert info['command'] == '/bin/daemon -d'
    assert info['running_time'] == '0h 1m 1s'


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
