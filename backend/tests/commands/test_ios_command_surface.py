"""iOS Command/ACMD registration follows the Pythonista capability boundary."""

from client.commands.platform.ios import iOSCommands
from client.commands.arguments.registry import ArgumentCommandRegistry


class DummyConnection:
    pass


def test_ios_manifest_exposes_new_names_only():
    commands = iOSCommands(DummyConnection())
    names = {item['name'] for item in commands.get_command_manifest_payload()}
    renamed = {
        'clear_console', 'keep_awake', 'kill_app', 'open_in', 'quick_look',
        'pick_upload', 'get_location', 'list_contacts',
    }
    removed = {
        'clearconsole', 'keepawake', 'killapp', 'openin', 'quicklook',
        'pickupload', 'getlocation', 'listcontacts', 'mkdir', 'rm', 'rmdir',
        'shell', 'shell_stream', 'bgrun', 'is_elevated', 'piplist',
        'keyboard_send', 'userenum', 'spawn_instance',
        'relaunch_instance', 'reexec_instance', 'acmd ps', 'acmd kill',
    }
    assert renamed <= names
    assert not (removed & names)
    assert {'getinfo', 'uptime', 'acmd ping', 'acmd help'} <= names
    assert {entry['group'] for entry in commands.get_command_manifest_payload() if entry['name'] in ('getinfo', 'uptime')} == {'system'}
    assert len(names) == len(commands.get_command_manifest_payload())


def test_ios_acmd_registry_and_help_do_not_expose_process_commands():
    commands = iOSCommands(DummyConnection())
    registry = ArgumentCommandRegistry(commands)
    assert not registry.has_command('ps')
    assert not registry.has_command('kill')
    assert registry.has_command('ping')
    assert 'ps' not in {item['name'] for item in registry.list_command_entries()}


def test_ios_unknown_shell_fallback_is_bounded_to_error():
    commands = iOSCommands(DummyConnection())
    assert commands.shell('echo hi')[0] == 0
    assert 'unavailable on iOS' in commands.shell('echo hi')[1]
    for name in ('shell', 'shell_stream', 'bgrun', 'is_elevated', 'piplist',
                 'spawn_instance', 'relaunch_instance', 'reexec_instance'):
        assert not hasattr(getattr(commands, name), 'help')


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
