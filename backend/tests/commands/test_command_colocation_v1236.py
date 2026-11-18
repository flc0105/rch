"""Regressions for command-owned implementation and genuinely shared capabilities."""
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.shell.base import CommandContext
from client.commands.shell.discovery import discover_shell_functions


@pytest.mark.parametrize('platform', ('mac', 'win', 'linux', 'ios'))
def test_argument_specs_come_from_registration_module(platform):
    registry = ArgumentCommandRegistry(CommandContext(SimpleNamespace(), platform), platform)
    for entry in registry._entries.values():
        handler = entry['handler']
        spec = entry['spec']
        if spec is not None:
            assert spec.__class__.__module__ == 'core.commands.argument_models'
            assert spec in vars(importlib.import_module(handler.__module__)).values(), (
                platform, handler.__module__, spec.name,
            )


def test_network_implementation_is_command_local_not_platform_adapter():
    from client.commands.acmd.common import _network, _network_native, network
    assert network.NETSTAT_ARGUMENT_SPEC in vars(network).values()
    assert network.IFCONFIG_ARGUMENT_SPEC in vars(network).values()
    assert _network.collect_ifconfig_rows.__module__.startswith('client.commands.acmd.common.')
    assert _network_native.PsutilNetstatProvider.__module__.startswith('client.commands.acmd.common.')
    assert _network_native.GetifaddrsIfconfigProvider.__module__.startswith('client.commands.acmd.common.')
    from client.platform.adapters import shared
    assert not hasattr(shared, 'PsutilNetstatProvider')
    assert not hasattr(shared, 'GetifaddrsIfconfigProvider')


def test_real_cross_consumer_process_service_is_preserved():
    from client.services.process import ProcessService
    ctx = CommandContext(SimpleNamespace(), 'linux')
    assert isinstance(ctx.process_service, ProcessService)
    assert ctx.process_service.adapter is ctx.adapter
    assert not hasattr(ctx, 'services')


@pytest.mark.parametrize('platform', ('mac', 'win', 'linux', 'ios'))
def test_existing_shell_and_acmd_names_survive(platform):
    expected_shell = {
        'mac': ('getinfo', 'screenshot', 'run_elevated'),
        'win': ('getinfo', 'screenshot', 'run_elevated'),
        'linux': ('getinfo', 'run_detached'),
        'ios': ('getinfo', 'ls', 'cat', 'list_contacts'),
    }
    ctx = CommandContext(SimpleNamespace(), platform)
    shell = discover_shell_functions(platform)
    assert set(expected_shell[platform]) <= set(shell)
    registry = ArgumentCommandRegistry(ctx, platform)
    assert 'ifconfig' in registry._entries
    assert ('netstat' in registry._entries) == (platform != 'ios')
    assert ('ps' in registry._entries) == (platform != 'ios')
    if platform == 'ios':
        assert {'find', 'tree', 'head', 'tail', 'wget'} <= set(registry._entries)


def test_ios_shell_file_operations_are_local(tmp_path):
    from client.commands.shell.platform import ios
    path = tmp_path / 'one.txt'
    assert ios.touch(None, str(path))[0] == 1
    path.write_text('alpha\nbeta\n', encoding='utf-8')
    assert ios.cat(None, str(path)) == (1, 'alpha\nbeta\n')
    assert 'one.txt' in ios.ls(None, str(tmp_path))[1]
    assert 'one.txt' in ios.md5sum(None, str(path))[1]
    assert ios.cat(None, str(tmp_path))[0] == 0


def test_ios_acmd_file_operations_are_local(tmp_path):
    from client.commands.acmd.platform import ios
    path = tmp_path / 'local.txt'
    path.write_text('one\ntwo\nthree\n', encoding='utf-8')
    assert ios.head(None, {'path': str(path), 'lines': 2}) == (1, 'one\ntwo')
    assert ios.tail(None, {'path': str(path), 'lines': 1}) == (1, 'three')
    assert ios.tree(None, {'path': str(tmp_path), 'max_depth': 1})[0] == 1
    assert str(path) in ios.find(None, {'path': str(tmp_path), 'keyword': 'local'})[1]
    assert ios.head(None, {'path': str(path), 'lines': -1})[0] == 0
