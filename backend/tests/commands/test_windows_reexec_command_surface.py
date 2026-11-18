"""The Windows command surface omits the POSIX process-replacement command."""

from client.commands.runtime.hosts import WindowsCommands
from client.commands.runtime.hosts import MacCommands
from client.commands.runtime.hosts import LinuxCommands
from client.commands.shell.runner import ShellCommandRunner
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
    assert not hasattr(commands.reexec_instance, 'help')
    assert commands.reexec_instance() == (0, 'Process replacement is unavailable on Windows')
    assert ShellCommandRunner(None)._resolve_builtin_command(commands, 'reexec_instance') is None


def test_posix_platforms_keep_reexec_command():
    for command_type in (MacCommands, LinuxCommands):
        commands = command_type(DummyConnection())
        catalog = CommandCatalog(DummyConnection())
        catalog._get_platform_name = lambda platform=command_type: 'mac' if platform is MacCommands else 'linux'
        names = {item['name'] for item in catalog.get_command_manifest_payload()}
        assert 'reexec_instance' in names
        assert 'relaunch_instance' in names
        assert hasattr(commands.reexec_instance, 'help')
