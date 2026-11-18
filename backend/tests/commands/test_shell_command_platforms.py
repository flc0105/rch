"""Shell registration metadata and platform restriction regressions."""

import pytest

from client.commands.shell.decorators import shell_command, supports_shell_platform
from client.commands.shell.runner import ShellCommandRunner
from client.commands.runtime.catalog import CommandCatalog
from client.commands.runtime.manifest_metadata import command_metadata


def test_shell_decorator_exposes_legacy_metadata_and_normalized_platforms():
    @shell_command('Example', group='system', output='stream', interaction=True,
                   platforms=('darwin', 'windows'))
    def example(self, arg=''):
        return 1, arg

    assert example.help == 'Example'
    assert example.group == 'system'
    assert example.command_output == 'stream'
    assert command_metadata(example)['interaction']['may_request'] is True
    assert example.command_platforms == ('mac', 'win')
    assert supports_shell_platform(example, 'win')
    assert supports_shell_platform(example, 'mac')
    assert not supports_shell_platform(example, 'ios')


def test_shell_platform_defaults_to_all_and_rejects_invalid_values():
    @shell_command('All platforms')
    def universal(self):
        return 1, 'ok'

    assert all(supports_shell_platform(universal, p)
               for p in ('mac', 'win', 'linux', 'ios'))
    for platforms in ((), ('bad',), ('mac', 'bad')):
        with pytest.raises(ValueError):
            shell_command('Invalid', platforms=platforms)
    with pytest.raises(TypeError):
        shell_command('Invalid', platforms='mac')


def test_known_but_unsupported_shell_command_is_not_fallback():
    class Commands:
        command_platform = 'win'

        @shell_command('macOS only', platforms=('mac',))
        def mac_only(self):
            raise AssertionError('wrong platform should never execute')

    resolved = ShellCommandRunner(None)._resolve_builtin_command(Commands(), 'mac_only')
    assert callable(resolved)
    assert resolved() == (0, 'Command not supported on this platform: mac_only')
    assert ShellCommandRunner(None)._resolve_builtin_command(Commands(), 'unknown') is None


def test_catalog_manifest_filters_restricted_shell_methods():
    class Commands:
        def __init__(self, socket):
            self.socket = socket

        @shell_command('Universal')
        def shared(self):
            return 1, ''

        @shell_command('Mac only', platforms=('mac',))
        def private(self):
            return 1, ''

    catalog = CommandCatalog(None)
    catalog._get_platform_name = lambda: 'win'
    catalog._load_platform_command_class = lambda: Commands
    names = {item['name'] for item in catalog.get_command_manifest_payload()}
    assert 'shared' in names
    assert 'private' not in names
    assert 'acmd help' in names
