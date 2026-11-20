"""PS and kill commands are two standalone handlers with one Common owner."""
import json
from types import SimpleNamespace

import pytest

from client.commands.acmd.common.process import ACMDProcessCommands
from client.commands.acmd.standalone.ps import ps, PS_ARGUMENT_SPEC
from client.commands.acmd.standalone.kill import kill, KILL_ARGUMENT_SPEC
from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.runtime.hosts import MacCommands, WindowsCommands, LinuxCommands, iOSCommands
from client.commands.runtime.catalog import CommandCatalog
from client.runtime.execution.process.process_service import ProcessService
from client.runtime.execution.process import approved_process_service as approved
from server.application.command.command_planner import CommandPlanner


def run(command, platform=LinuxCommands):
    host = platform(socket=SimpleNamespace())
    registry = ArgumentCommandRegistry(host)
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(command)
    return registry.execute(payload)


def test_common_class_only_mounts_standalone_functions():
    assert ACMDProcessCommands.ps is ps
    assert ACMDProcessCommands.kill is kill
    assert set(key for key in ACMDProcessCommands.__dict__ if not key.startswith('__')) == {'ps', 'kill', 'wait_pid'}
    assert ps.argument_command_spec is PS_ARGUMENT_SPEC
    assert kill.argument_command_spec is KILL_ARGUMENT_SPEC
    assert kill.command_interaction is True
    assert ps.argument_command_platforms == kill.argument_command_platforms == ('mac', 'win', 'linux')


@pytest.mark.parametrize('platform', [MacCommands, WindowsCommands, LinuxCommands])
def test_desktop_one_entry_each_and_ios_none(platform):
    registry = ArgumentCommandRegistry(platform(socket=SimpleNamespace()))
    assert {'ps', 'kill'} <= set(registry._entries)
    assert registry._entries['ps']['handler'].__func__ is ps
    assert registry._entries['kill']['handler'].__func__ is kill
    assert sum(k == 'ps' for k in registry._entries) == 1
    assert sum(k == 'kill' for k in registry._entries) == 1
    ios = ArgumentCommandRegistry(iOSCommands(socket=SimpleNamespace()))
    assert 'ps' not in ios._entries and 'kill' not in ios._entries


def test_ps_filters_json_actions_and_text(monkeypatch):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda self: [
        {'pid': 77, 'ppid': 1, 'name': 'Python worker', 'username': 'user', 'status': 'running'},
        {'pid': 9, 'ppid': 1, 'name': 'other', 'username': 'user', 'status': 'sleeping'},
    ])
    status, body = run('acmd ps --name python --json --with-actions')
    assert status == 1
    assert json.loads(body) == [{
        'pid': 77, 'ppid': 1, 'name': 'Python worker', 'username': 'user',
        'status': 'running', '_actions': [{'label': 'Kill', 'command': 'acmd kill --pid 77'}]
    }]
    status, body = run('acmd ps --pid 9')
    assert status == 1 and 'other' in body and 'Python worker' not in body
    status, body = run('acmd ps --name absent')
    assert status == 0 and 'No process found for name absent' in body


def test_ps_port_uses_shared_verified_port_owners(monkeypatch):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda self: [
        {'pid': 77, 'ppid': 1, 'name': 'service', 'username': 'u', 'status': 'sleeping'},
    ])
    monkeypatch.setattr(approved, 'port_owners', lambda port: {77} if port == 22002 else set())
    assert run('acmd ps --port 22002 --json')[0] == 1
    assert run('acmd ps --port 22003')[0] == 0
    status, body = run('acmd ps --port 65536')
    assert status == 0 and '1..65535' in body


def test_kill_no_confirm_requires_target_and_checks_identity(monkeypatch):
    row = {'pid': 8081, 'name': 'test-app'}
    events = []
    monkeypatch.setattr(approved, 'find_targets', lambda criteria, **kwargs: events.append(('found', criteria)) or [row])
    monkeypatch.setattr(approved, 'terminate_verified', lambda target, *, force, port=None:
                        events.append(('verified', target['pid'], force, port)) or 'SIGKILL')
    # Neither a real system process nor an Interaction Broker is contacted.
    assert run('acmd kill --no-confirm')[0] == 0
    assert events == []
    host = LinuxCommands(socket=SimpleNamespace())
    host._set_timeout = lambda seconds: None
    host._checkpoint = lambda **kwargs: None
    registry = ArgumentCommandRegistry(host)
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(
        'acmd kill --pid 8081 --no-confirm --force')
    status, output = registry.execute(payload)
    assert status == 1 and 'SIGKILL sent to PID 8081' in output
    assert events == [('found', {'pid': 8081}), ('verified', 8081, True, None)]


def test_kill_preview_selection_and_force(monkeypatch):
    row = {'pid': 8081, 'name': 'test-app'}
    events = []
    monkeypatch.setattr(approved, 'find_targets', lambda criteria, **kwargs: [row])
    monkeypatch.setattr(approved, 'build_multi_preview', lambda rows, **kwargs: {'row_ids': ['8081']})
    class FakeUI:
        def __init__(self, owner): pass
        def approve_processes(self, message, preview):
            events.append(('approval', message))
            return {'8081'}, False
    monkeypatch.setattr(approved, 'ClientCommandInteractions', FakeUI)
    monkeypatch.setattr(approved, 'terminate_verified', lambda row, *, force, port=None:
                        events.append(('signal', row['pid'], force)) or 'SIGTERM')
    host = LinuxCommands(socket=SimpleNamespace())
    host._set_timeout = lambda seconds: None
    host._checkpoint = lambda **kwargs: None
    registry = ArgumentCommandRegistry(host)
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command('acmd kill --pid 8081')
    status, body = registry.execute(payload)
    assert status == 1 and 'SIGTERM sent to PID 8081' in body
    assert events == [('approval', 'Approve termination of selected Client processes?'), ('signal', 8081, False)]


def test_kill_no_signal_on_rejected_selection_or_invalid_criteria(monkeypatch):
    row = {'pid': 8081, 'name': 'test-app'}
    monkeypatch.setattr(approved, 'find_targets', lambda criteria, **kwargs: [row])
    monkeypatch.setattr(approved, 'build_multi_preview', lambda rows, **kwargs: {'row_ids': ['8081']})
    class FakeUI:
        def __init__(self, owner): pass
        def approve_processes(self, message, preview): return set(), False
    monkeypatch.setattr(approved, 'ClientCommandInteractions', FakeUI)
    monkeypatch.setattr(approved, 'terminate_verified', lambda *a, **k: (_ for _ in ()).throw(AssertionError('should not signal')))
    host = LinuxCommands(socket=SimpleNamespace())
    host._set_timeout = lambda seconds: None
    host._checkpoint = lambda **kwargs: None
    registry = ArgumentCommandRegistry(host)
    def execute(raw):
        return registry.execute(CommandPlanner.__new__(CommandPlanner).parse_argument_command(raw))
    assert execute('acmd kill --pid 8081')[0] == 1
    assert 'No processes selected' in execute('acmd kill --pid 8081')[1]
    assert execute('acmd kill --pid 8081 --port 8000')[0] == 0
    assert execute('acmd kill --port 70000 --no-confirm')[0] == 0


@pytest.mark.parametrize('platform_name, platform', [
    ('mac', MacCommands), ('win', WindowsCommands), ('linux', LinuxCommands), ('ios', iOSCommands),
])
def test_new_background_shell_names_are_canonical(platform_name, platform):
    from client.commands.shell.common.execution import ShellExecutionCommands
    assert callable(ShellExecutionCommands.shell_bg)
    assert callable(ShellExecutionCommands.run_bg)
    catalog = CommandCatalog(SimpleNamespace())
    catalog._get_platform_name = lambda: platform_name
    manifest = catalog.get_command_manifest_payload()
    names = {row['name'] for row in manifest}
    assert 'bgrun' not in names and 'run_detached' not in names
    if platform_name == 'ios':
        assert 'shell_bg' not in names and 'run_bg' not in names
    else:
        assert {'shell_bg', 'run_bg'} <= names


def test_kill_revalidation_blocks_pid_reuse_and_port_reassignment(monkeypatch):
    import psutil
    from client.runtime.execution.process.approved_process_service import ProcessApprovalError
    signals = []

    class FakeProcess:
        def create_time(self): return 101.0
        def name(self): return 'test-app'
        def exe(self): return '/bin/test-app'
        def terminate(self): signals.append('TERM')
        def kill(self): signals.append('KILL')

    monkeypatch.setattr(psutil, 'Process', lambda pid: FakeProcess())
    original = {'pid': 8081, 'created_at': 100.0, 'name': 'test-app', 'exec_path': '/bin/test-app'}
    with pytest.raises(ProcessApprovalError, match='identity changed'):
        approved.terminate_verified(original, force=False)
    assert signals == []

    original['created_at'] = 101.0
    monkeypatch.setattr(approved, 'port_owners', lambda port: set())
    with pytest.raises(ProcessApprovalError, match='no longer owns'):
        approved.terminate_verified(original, force=True, port=8808)
    assert signals == []
