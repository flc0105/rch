"""iOS Command/ACMD registration follows the Pythonista capability boundary."""

from client.commands.runtime.hosts import iOSCommands
from client.commands.shell.decorators import supports_shell_platform
from client.commands.shell.platform.ios import iOSShellCommands
from client.commands.shell.runner import ShellCommandRunner
from client.commands.runtime.executor import CommandExecutor
from client.commands.runtime.catalog import CommandCatalog
from client.commands.acmd.registry import ArgumentCommandRegistry


class DummyConnection:
    pass


def test_ios_manifest_exposes_new_names_only():
    commands = iOSCommands(DummyConnection())
    catalog = CommandCatalog(DummyConnection())
    catalog._get_platform_name = lambda: 'ios'
    manifest = catalog.get_command_manifest_payload()
    names = {item['name'] for item in manifest}
    renamed = {
        'clear_console', 'keep_awake', 'get_location', 'list_contacts',
        'list_reminders',
    }
    removed = {
        'openurl', 'open_in', 'quick_look', 'pick_upload', 'kill_app',
        'clearconsole', 'keepawake', 'killapp', 'openin', 'quicklook',
        'pickupload', 'getlocation', 'listcontacts', 'mkdir', 'rm', 'rmdir',
        'shell', 'shell_stream', 'shell_bg', 'run_bg', 'is_elevated', 'piplist',
        'keyboard_send', 'userenum', 'spawn_instance',
        'relaunch_instance', 'reexec_instance', 'acmd ps', 'acmd kill',
        'acmd ping', 'acmd tcp_ping',
    }
    assert renamed <= names
    assert not (removed & names)
    assert {'getinfo', 'uptime', 'acmd help'} <= names
    device = {'clipboard_read', 'clipboard_write', 'get_location', 'speak', 'list_contacts', 'list_reminders'}
    assert {entry['group'] for entry in manifest if entry['name'] in device} == {'device'}
    assert {entry['group'] for entry in manifest if entry['name'] in ('getinfo', 'uptime')} == {'system'}
    assert len(names) == len(manifest)


def test_ios_acmd_registry_and_help_do_not_expose_process_commands():
    commands = iOSCommands(DummyConnection())
    registry = ArgumentCommandRegistry(commands)
    assert not registry.has_command('ps')
    assert not registry.has_command('kill')
    assert not registry.has_command('ping')
    assert not registry.has_command('tcp_ping')
    assert 'ps' not in {item['name'] for item in registry.list_command_entries()}


def test_ios_unknown_shell_fallback_is_bounded_to_error():
    commands = iOSCommands(DummyConnection())
    # OS Shell methods no longer have iOS overrides; the metadata owns eligibility.
    for name in ('shell', 'shell_stream', 'shell_bg', 'run_bg'):
        assert name not in iOSShellCommands.__dict__
        assert not supports_shell_platform(getattr(commands, name), 'ios')
        rejected = ShellCommandRunner(None)._resolve_builtin_command(commands, name)
        assert rejected is not None
        assert rejected()[0] == 0

    fallback = ShellCommandRunner(None)._resolve_default_command(commands, 'echo hi')
    assert fallback() == (0, 'OS shell execution is unavailable on this platform')
    for name in ('is_elevated', 'piplist', 'keyboard_send', 'userenum',
                 'spawn_instance', 'relaunch_instance', 'reexec_instance'):
        assert name not in iOSShellCommands.__dict__
        assert not supports_shell_platform(getattr(commands, name), 'ios')
        assert ShellCommandRunner(None)._resolve_builtin_command(commands, name)()[0] == 0



def test_ios_shell_platform_gate_blocks_dispatch_and_os_fallback():
    executor = CommandExecutor(DummyConnection())
    executor.catalog._get_platform_name = lambda: 'ios'
    for command_name, argument in (
        ('shell', 'echo not-executed'),
        ('shell_stream', 'echo not-executed'),
        ('shell_bg', 'echo not-executed'),
        ('run_bg', '/usr/bin/true'),
    ):
        status, output = executor.execute_command(
            f'guard_{command_name}', f'{command_name} {argument}'
        )
        assert status == 0
        assert output == f'Command not supported on this platform: {command_name}'
    assert executor.execute_command('guard_unknown', 'rch_nonexistent_cli_987654') == (
        0, 'OS shell execution is unavailable on this platform'
    )
    assert executor.execute_command('guard_ios_builtin', 'echo hello') == (1, 'hello')


def test_ios_uptime_uses_native_process_info_and_desktop_output_shape(monkeypatch):
    import sys
    import types

    seconds = 2 * 86400 + 3 * 3600 + 4 * 60 + 21
    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(
        ObjCClass=lambda name: types.SimpleNamespace(
            processInfo=lambda: types.SimpleNamespace(systemUptime=lambda: seconds))))
    commands = iOSCommands(DummyConnection())
    status, output = commands.uptime()
    assert status == 1
    assert output.startswith('Boot time: ')
    assert output.endswith('\nUptime: 2d 3h 4m')


def test_ios_uptime_returns_command_error_on_native_failure(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(
        ObjCClass=lambda name: (_ for _ in ()).throw(RuntimeError('unavailable'))))
    status, output = iOSCommands(DummyConnection()).uptime()
    assert status == 0
    assert 'unavailable' in output


def test_ping_scripts_remain_independent_of_removed_command_utilities():
    from pathlib import Path
    scripts_root = Path(__file__).resolve().parents[2] / 'server/resources/scripts/ios/network'
    for name in ('icmp_ping.py', 'tcp_ping.py'):
        assert (scripts_root / name).is_file()
    services = Path(__file__).resolve().parents[2] / 'client/commands/platform'
    assert not (services / 'services/ios/network_service.py').exists()
    assert not (services / 'utils/network_util.py').exists()
