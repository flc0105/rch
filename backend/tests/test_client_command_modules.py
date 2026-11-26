"""Command owner modules, explicit ACMD registration, and execution regressions."""

import inspect
from types import SimpleNamespace

import pytest

from client.commands.acmd.decorators import argument_command
from client.commands.runtime.catalog import CommandCatalog
from client.commands.runtime.executor import CommandExecutor
from client.commands.shell.decorators import shell_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec


@pytest.fixture(params=['mac', 'win', 'linux', 'ios'])
def catalog(request):
    result = CommandCatalog(SimpleNamespace(send_event=lambda *_args, **_kwargs: None))
    result._get_platform_name = lambda: request.param
    return result


def test_platform_command_counts_and_owners(catalog):
    counts = {'mac': (28, 22), 'win': (27, 21), 'linux': (23, 17), 'ios': (26, 20)}
    platform = catalog._get_platform_name()
    shell = catalog.get_exported_shell_commands()
    acmd = catalog.get_argument_command_registry()
    assert (len(shell), len(acmd._entries)) == counts[platform]
    assert 'cd' in shell and 'getinfo' in shell and 'pyexec' in shell
    assert 'download' in acmd._entries and 'zip' in acmd._entries
    assert ('webcam_snap' in shell) == (platform == 'mac')
    assert ('run' in shell) == (platform == 'win')
    assert ('ls' in shell) == (platform == 'ios')
    assert ('launchd' in acmd._entries) == (platform == 'mac')
    assert ('ps' in acmd._entries) == (platform != 'ios')
    assert ('clipboard_read' in acmd._entries) == (platform != 'linux')
    assert inspect.signature(catalog.get_shell_command('cd')).parameters['path']
    assert inspect.signature(acmd._entries['download']['handler']).parameters['args_dict']
    assert catalog.get_shell_command('getinfo').__func__.__module__.endswith('standalone.getinfo')
    assert catalog.get_shell_command('getpid').__func__.__module__.endswith('common.system')


def test_manifest_and_help_derive_from_same_specs(catalog):
    manifest = catalog.get_command_manifest_payload()
    names = [item['name'] for item in manifest]
    assert len(names) == len(set(names))
    assert 'acmd help' in names and 'getpid' in names
    registry = catalog.get_argument_command_registry()
    assert {f'acmd {name}' for name in registry._entries} <= set(names)
    assert 'download' not in names
    status, help_text = registry.execute({'name': 'download', 'args': {'help': True}})
    assert status == 1 and '--path' in help_text
    status, help_text = registry.execute({'name': 'help', 'args': {'_args': ['download']}})
    assert status == 1 and '--path' in help_text
    status, message = registry.execute({'name': 'unknown', 'args': {}})
    assert (status, message) == (0, 'acmd command not supported on this platform: unknown')


def test_standalone_import_is_not_ownership(catalog, monkeypatch):
    from client.commands.shell.standalone import getinfo as shell_standalone
    from client.commands.acmd.standalone import drives as acmd_standalone

    @shell_command('Unused command')
    def never_mounted(scope):
        return 1, 'unused'

    spec = ArgumentCommandSpec('never_registered', 'Unused command',
                               [ArgumentOptionSpec('help', 'flag', default=False)])

    @argument_command('never_registered', spec=spec)
    def never_registered(scope, args):
        return 1, 'unused'

    monkeypatch.setattr(shell_standalone, 'never_mounted', never_mounted, raising=False)
    monkeypatch.setattr(acmd_standalone, 'never_registered', never_registered, raising=False)
    assert catalog.get_shell_command('never_mounted') is None
    assert 'never_registered' not in catalog.get_argument_command_registry()._entries


def test_duplicate_and_invalid_spec_fail(catalog):
    registry = catalog.get_argument_command_registry()
    handler = registry._entries['download']['handler'].__func__
    with pytest.raises(ValueError, match='Duplicate ACMD'):
        registry.register(handler)
    with pytest.raises(ValueError, match='matching'):
        registry.register(lambda args: None)


def test_platform_admission_follows_existing_filters(catalog):
    platform = catalog._get_platform_name()
    assert ('idletime' in catalog.get_exported_shell_commands()) == (platform in ('mac', 'win'))
    assert ('drives' in catalog.get_argument_command_registry()._entries) == (platform != 'ios')
    if platform == 'linux':
        from client.commands.shell.runner import ShellCommandRunner
        runner = ShellCommandRunner(SimpleNamespace(catalog=catalog))
        status, message = runner._resolve_builtin_command(catalog.get_commands(), 'idletime')()
        assert status == 0 and message == 'Command not supported on this platform: idletime'


def test_linux_runtime_execution_and_completion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'sample-report.txt').write_text('hello')
    executor = CommandExecutor(SimpleNamespace(send_event=lambda *_args, **_kwargs: None))
    executor.catalog._get_platform_name = lambda: 'linux'
    status, output = executor.execute_command('getpid-check', 'getpid')
    assert status == 1 and str(output).isdigit()
    status, output = executor.execute_command('pwd-check', 'pwd')
    assert status == 1 and str(tmp_path) in output
    status, output = executor.execute_argument_command('tcp-check', {
        'name': 'tcp_check', 'args': {'port': '0'},
    })
    assert status == 0 and '--port must be between 1 and 65535' in output
    suggestion = executor.complete_command_completion({
        'raw_input': 'acmd download sample-re',
        'cursor_position': len('acmd download sample-re'),
    })
    assert any(item['insert_text'] == 'acmd download sample-report.txt'
               for item in suggestion['items'])
    names = executor.sdk_command_names()
    assert 'getpid' in names and 'idletime' not in names
    scope = SimpleNamespace(command_id='sdk-check', execution_context=None)
    assert executor.resolve_sdk_command(scope, 'getpid')()[0] == 1


def test_acmd_standalone_zip_unzip_and_shell_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source.txt'
    source.write_text('RCH command module regression')
    destination = tmp_path / 'restored'
    destination.mkdir()
    executor = CommandExecutor(SimpleNamespace(send_event=lambda *_args, **_kwargs: None))
    executor.catalog._get_platform_name = lambda: 'linux'

    status, output = executor.execute_argument_command('zip-case', {
        'name': 'zip', 'args': {'path': str(source)}, 'raw': 'acmd zip source.txt',
    })
    assert status == 1 and '[+] ZIP complete' in output
    archive_path = tmp_path / 'source.txt.zip'
    assert archive_path.is_file()

    status, output = executor.execute_argument_command('unzip-case', {
        'name': 'unzip', 'args': {'path': str(archive_path), 'dest': str(destination)},
        'raw': 'acmd unzip source.txt.zip --dest restored',
    })
    assert status == 1 and '[+] UNZIP complete' in output
    assert (destination / 'source.txt' / 'source.txt').read_text() == source.read_text()

    status, output = executor.execute_command('pyexec-case', 'pyexec print(6 * 7)')
    assert status == 1 and output.strip() == '42'
