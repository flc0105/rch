"""Platform registration and execution of desktop Shell commands."""

from unittest.mock import Mock

import pytest

from client.commands.runtime.executor import CommandExecutor
from client.commands.runtime.hosts import WindowsCommands
from client.commands.runtime.hosts import MacCommands
from client.commands.runtime.hosts import LinuxCommands
from client.commands.shell.runner import ShellCommandRunner
from client.commands.shell.platform.win import WindowsShellCommands
from client.commands.runtime.catalog import CommandCatalog


class DummyConnection:
    pass


def test_windows_does_not_register_reexec_command():
    commands = WindowsCommands(DummyConnection())
    catalog = CommandCatalog(DummyConnection())
    catalog._get_platform_name = lambda: 'win'
    names = {item['name'] for item in catalog.get_command_manifest_payload()}
    assert 'reexec_instance' not in names
    assert 'relaunch_instance' in names
    assert 'reexec_instance' not in WindowsShellCommands.__dict__
    rejected = ShellCommandRunner(None)._resolve_builtin_command(commands, 'reexec_instance')
    assert rejected() == (0, 'Command not supported on this platform: reexec_instance')


def test_posix_platforms_keep_reexec_command():
    for command_type in (MacCommands, LinuxCommands):
        commands = command_type(DummyConnection())
        catalog = CommandCatalog(DummyConnection())
        catalog._get_platform_name = lambda platform=command_type: 'mac' if platform is MacCommands else 'linux'
        names = {item['name'] for item in catalog.get_command_manifest_payload()}
        assert 'reexec_instance' in names
        assert 'relaunch_instance' in names
        assert hasattr(commands.reexec_instance, 'help')


def test_common_desktop_commands_preserve_platform_registration_and_budgets():
    from client.commands.runtime.hosts import iOSCommands
    from client.commands.shell.common.system import ShellSystemCommands

    expected = {'win': (10, 150, 150), 'mac': (None, 150, 150), 'linux': None, 'ios': None}
    names = ('idletime', 'run_elevated', 'spawn_elevated_instance')
    for command_type in (WindowsCommands, MacCommands, LinuxCommands, iOSCommands):
        host = command_type(DummyConnection())
        catalog = CommandCatalog(DummyConnection())
        catalog.platform_commands = host
        catalog._get_platform_name = lambda: host.command_platform
        entries = {item['name']: item for item in catalog.get_command_manifest_payload()}
        timeouts = expected[host.command_platform]
        for name in names:
            assert getattr(host, name).__func__ is ShellSystemCommands.__dict__[name]
            assert (name in entries) == (timeouts is not None)
        if timeouts is not None:
            assert tuple(entries[item]['timeout'] for item in names) == timeouts
            for name in names[1:]:
                assert entries[name]['confirmation'] is True


def test_common_elevated_command_confirms_native_platform_and_protects_payload(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from client.commands.shell.standalone import run_elevated
    from client.runtime.execution import interaction_service

    approve = Mock(return_value=False)
    launch = Mock(return_value=(1, 'ok'))
    monkeypatch.setattr(interaction_service, 'CommandInteractions', lambda _: SimpleNamespace(confirm=approve))
    monkeypatch.setattr(run_elevated.WindowsElevation, 'shell', launch)
    monkeypatch.setattr(run_elevated.MacElevation, 'shell', launch)
    assert WindowsCommands(None).run_elevated('echo check')[0] == 0
    assert 'Windows UAC' in approve.call_args.args[0]
    assert MacCommands(None).run_elevated('echo check')[0] == 0
    assert 'operating system permission prompt' in approve.call_args.args[0]
    launch.assert_not_called()

    assert WindowsCommands(None).run_elevated('echo check --no-confirm') == (1, 'ok')
    launch.assert_called_once_with('echo check')
    assert MacCommands(None).run_elevated('--shell -- echo keep --no-confirm')[0] == 0
    assert MacCommands(None).run_elevated('--no-confirm --shell -- echo keep --no-confirm') == (1, 'ok')
    launch.assert_called_with('echo keep --no-confirm')


@pytest.mark.parametrize('platform', ['win', 'mac'])
def test_spawn_no_confirm_works_from_terminal_and_is_listed_in_help(monkeypatch, platform):
    from client.commands.shell.standalone import spawn_elevated_instance as module
    from client.runtime.execution.interaction_service import CommandInteractions

    runner = CommandExecutor(DummyConnection())
    monkeypatch.setattr(runner.catalog, '_get_platform_name', lambda: platform)
    launch = Mock(return_value=(1, 'Elevated Client started'))
    confirm = Mock(return_value=False)
    monkeypatch.setattr(module, '_spawn_elevated_' + platform, launch)
    monkeypatch.setattr(CommandInteractions, 'confirm', confirm)

    entry = next(item for item in runner.get_command_manifest_payload()
                 if item['name'] == 'spawn_elevated_instance')
    assert '--no-confirm' in entry['help']
    assert entry['confirmation'] is True

    assert runner.execute_command(1, 'spawn_elevated_instance --no-confirm') == (1, 'Elevated Client started')
    launch.assert_called_once()
    confirm.assert_not_called()

    launch.reset_mock()
    assert runner.execute_command(2, 'spawn_elevated_instance --detached --no-confirm') == (
        0, 'Usage: spawn_elevated_instance [--no-confirm]',
    )
    launch.assert_not_called()
    confirm.assert_not_called()

    assert runner.execute_command(3, 'spawn_elevated_instance')[0] == 0
    confirm.assert_called_once()
    launch.assert_not_called()


def test_windows_run_uses_detached_console_from_platform_entry(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from unittest.mock import Mock

    spawn = Mock(return_value=SimpleNamespace(pid=101))
    monkeypatch.setattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    host = WindowsCommands(None)
    assert host.run('') == (0, 'Usage: run <program ...>')
    assert host.run('cmd.exe /c exit') == (1, 'Process created: 101')
    assert spawn.call_args.args == ('cmd.exe /c exit',)
    assert spawn.call_args.kwargs['creationflags'] == subprocess.CREATE_NEW_CONSOLE
