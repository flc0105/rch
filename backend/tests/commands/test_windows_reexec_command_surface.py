"""The Windows command surface omits the POSIX process-replacement command."""

from client.commands.platform.win import WindowsCommands
from client.commands.platform.mac import MacCommands
from client.commands.platform.linux import LinuxCommands
from client.commands.runtime.shell_command_runner import ShellCommandRunner


class DummyConnection:
    pass


def test_windows_does_not_register_reexec_command():
    commands = WindowsCommands(DummyConnection())
    names = {item['name'] for item in commands.get_command_manifest_payload()}
    assert 'reexec_instance' not in names
    assert 'relaunch_instance' in names
    assert 'reexec_instance' not in commands._get_exported_command_methods()
    assert all('reexec_instance' not in str(entries) for entries in commands._group_command_help_payload().values())
    assert not hasattr(commands.reexec_instance, 'help')
    assert commands.reexec_instance() == (0, 'Process replacement is unavailable on Windows')
    assert ShellCommandRunner(None)._resolve_builtin_command(commands, 'reexec_instance') is None


def test_posix_platforms_keep_reexec_command():
    for command_type in (MacCommands, LinuxCommands):
        commands = command_type(DummyConnection())
        names = {item['name'] for item in commands.get_command_manifest_payload()}
        assert 'reexec_instance' in names
        assert 'relaunch_instance' in names
        assert hasattr(commands.reexec_instance, 'help')
