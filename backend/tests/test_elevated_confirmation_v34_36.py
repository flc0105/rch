"""Elevated Client launch semantics and opt-in confirmation bypass."""
import ctypes
from types import SimpleNamespace

import pytest

from core.utils.decorator import confirm, desc, _strip_confirm_bypass
from client.commands.platform.mac import MacCommands
from client.commands.platform.win import WindowsCommands
from client.commands.platform.services.win.privilege_service import WinPrivilegeService
from client.commands.common.services.interaction_service import CommandInteractions
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


@pytest.mark.parametrize('cls', [MacCommands, WindowsCommands])
def test_elevation_commands_are_declared_as_confirmed_and_opt_in(cls):
    for command in ('run_elevated', 'spawn_elevated_instance'):
        method = getattr(cls, command)
        assert method.group == 'privilege'
        assert method.requires_confirmation is True
        assert method.allow_no_confirm is True
        assert 'interactions:request' in method.api_grants


def test_no_confirm_works_without_interaction_service(monkeypatch):
    calls = []
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Broker contacted')))
    host = SimpleNamespace(win_privilege=SimpleNamespace(
        spawn_elevated_instance=lambda: (1, 'spawned'),
        run_as_admin=lambda value: calls.append(value) or (1, 'ran'),
    ))
    assert WindowsCommands.spawn_elevated_instance(host, '--no-confirm') == (1, 'spawned')
    assert WindowsCommands.run_elevated(host, '--no-confirm python3 app.py') == (1, 'ran')
    assert WindowsCommands.run_elevated(host, 'python3 app.py --no-confirm') == (1, 'ran')
    assert calls == ['python3 app.py', 'python3 app.py']
    assert WindowsCommands.spawn_elevated_instance(host, '--no-confirm unexpected')[0] == 0


def test_confirmation_rejects_before_elevated_operation(monkeypatch):
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: False)
    host = SimpleNamespace(mac_automation=SimpleNamespace(
        sudo_self=lambda: (_ for _ in ()).throw(AssertionError('should not spawn')),
        sudo_run=lambda value: (_ for _ in ()).throw(AssertionError('should not run')),
    ))
    for func, args in [(MacCommands.spawn_elevated_instance, ('',)), (MacCommands.run_elevated, ('echo test',))]:
        assert func(host, *args)[0] == 0


def test_mac_bypass_calls_existing_services(monkeypatch):
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Broker contacted')))
    host = SimpleNamespace(mac_automation=SimpleNamespace(sudo_self=lambda: (1, 'started'), sudo_run=lambda value: (1, value)))
    assert MacCommands.spawn_elevated_instance(host, '--no-confirm') == (1, 'started')
    assert MacCommands.run_elevated(host, '--no-confirm whoami') == (1, 'whoami')


def test_other_confirm_commands_are_not_bypassable(monkeypatch):
    requests = []
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: requests.append(a) or False)
    @confirm('Approve?')
    @desc('Guarded')
    def action(self, arg=''):
        return 1, arg
    assert action(SimpleNamespace(), '--no-confirm')[0] == 0
    assert len(requests) == 1


def test_windows_self_launch_uses_real_executable_and_uac(monkeypatch):
    from client.runtime import client_util
    monkeypatch.setattr(client_util, 'get_exec_and_args', lambda: (r'C:\Python\python.exe', r'"C:\proj\rchclient.py" --flag'))
    # Function imports the helper inside the method; fake Windows' native API on Linux.
    args = []
    fake_shell = SimpleNamespace(ShellExecuteW=lambda *params: args.append(params) or 42)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=fake_shell), raising=False)
    service = WinPrivilegeService(None)
    assert service.spawn_elevated_instance()[0] == 1
    assert args[0][1:4] == ('runas', r'C:\Python\python.exe', r'"C:\proj\rchclient.py" --flag')
    fake_shell.ShellExecuteW = lambda *params: 5
    assert service.spawn_elevated_instance()[0] == 0


def test_server_grant_not_issued_for_bypass_flag(monkeypatch):
    issued = []
    session = SimpleNamespace(
        session_info=SimpleNamespace(os_alias='win'),
        context=SimpleNamespace(script_grant_service=None),
    )
    channel = ClientSessionCommandChannel(session)
    monkeypatch.setattr(channel, '_build_script_grant_extra', lambda id, data: issued.append(data) or {'grant': 'set'})
    assert 'extra' not in channel.build_command_payload('spawn_elevated_instance --no-confirm')
    assert 'extra' not in channel.build_command_payload('run_elevated --no-confirm whoami')
    assert 'extra' not in channel.build_command_payload('run_elevated whoami --no-confirm')
    assert len(issued) == 0
    assert channel.build_command_payload('spawn_elevated_instance')['extra'] == {'grant': 'set'}
    assert channel.build_command_payload('run_elevated whoami')['extra'] == {'grant': 'set'}
    assert len(issued) == 2


def test_bypass_flag_recognized_only_as_command_option():
    assert _strip_confirm_bypass('--no-confirm ls') == (True, 'ls')
    assert _strip_confirm_bypass('ls --no-confirm') == (True, 'ls')
    assert _strip_confirm_bypass('echo --no-confirm still here') == (False, 'echo --no-confirm still here')


def test_shell_command_runner_executes_elevated_bypass_without_broker(monkeypatch):
    from client.commands.runtime.shell_command_runner import ShellCommandRunner

    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Broker contacted')))
    received = []
    host = SimpleNamespace(
        run_elevated=lambda arg: WindowsCommands.run_elevated(host, arg),
        win_privilege=SimpleNamespace(run_as_admin=lambda arg: received.append(arg) or (1, 'ok')),
    )
    # The actual runner resolves decorated platform methods by their exported metadata.
    host.run_elevated.help = WindowsCommands.run_elevated.help
    executor = SimpleNamespace(
        command_variable_resolver=SimpleNamespace(resolve=lambda text, **kw: text),
        execute_bound_request=lambda request, callback: callback(host),
    )
    result = ShellCommandRunner(executor).execute(SimpleNamespace(command_id=1), 'run_elevated --no-confirm whoami')
    assert result[0] == 1
    assert received == ['whoami']
