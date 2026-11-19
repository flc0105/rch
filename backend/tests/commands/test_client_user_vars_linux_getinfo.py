"""Client-scoped var namespace and Linux system information command."""
import json
import os
from types import SimpleNamespace

from client.runtime.command_variable_resolver import (
    CommandVariableResolver, CommandVariableResolutionError,
)
from client.commands.runtime.executor import CommandExecutor
from client.commands.runtime.hosts import LinuxCommands
from client.commands.shell.standalone import getinfo as info_module
from client.commands.shell.standalone import getinfo_collectors as probe_module
from core.utils.command_output import render_structured_result
import pytest


def test_user_variable_namespace_independent_of_environ(monkeypatch):
    monkeypatch.setenv('VAR_TEST', 'system-value')
    resolver = CommandVariableResolver(SimpleNamespace(client_id='a'))
    resolver.set_var('VAR_TEST', '123345')
    assert resolver.resolve('${var:VAR_TEST}|${env:VAR_TEST}') == '123345|system-value'
    assert os.environ['VAR_TEST'] == 'system-value'
    assert resolver.list_vars() == {'VAR_TEST': '123345'}
    assert resolver.unset_var('VAR_TEST') is True
    with pytest.raises(CommandVariableResolutionError, match='not set'):
        resolver.resolve('${var:VAR_TEST}')
    with pytest.raises(CommandVariableResolutionError, match='Invalid variable name'):
        resolver.set_var('123BAD', 'x')
    with pytest.raises(CommandVariableResolutionError, match='Unsupported variable namespace'):
        resolver.resolve('${unknown:FOO}')
    assert any(x['namespace'] == 'var' and x['template'] == '${var:NAME}'
               for x in resolver.get_manifest_payload())


def test_var_command_across_separate_commands_and_client_isolation(monkeypatch):
    from client.commands.runtime.catalog import CommandCatalog
    monkeypatch.setattr(CommandCatalog, '_get_platform_name', lambda _: 'linux')
    first = CommandExecutor(SimpleNamespace(client_id='client-a'))
    second = CommandExecutor(SimpleNamespace(client_id='client-b'))
    assert first.execute_command(101, 'var TOKEN=123345') == (1, 'TOKEN set')
    assert first.execute_command(102, 'var TOKEN=hello world') == (1, 'TOKEN set')
    assert first.execute_command(103, 'var') == (1, 'TOKEN=hello world')
    assert first.execute_command(104, 'var NEXT=${var:TOKEN}') == (1, 'NEXT set')
    assert first.command_variable_resolver.resolve('${var:NEXT}') == 'hello world'
    assert second.execute_command(105, 'var') == (1, 'No user variables')
    status, message = second.execute_command(106, 'var NEXT=${var:TOKEN}')
    assert status == 0 and 'not set' in message
    status, message = first.execute_command(107, 'var 9X=bad')
    assert status == 0 and 'Invalid variable name' in message
    assert first.execute_command(108, 'var --unset TOKEN') == (1, 'TOKEN removed')
    assert first.execute_command(109, 'var --unset TOKEN')[0] == 0
    assert first.execute_command(110, 'var NEXT=')[0] == 1
    assert first.command_variable_resolver.resolve('${var:NEXT}') == ''
    assert first.execute_command(111, 'var A=B=C') == (1, 'A set')
    assert first.command_variable_resolver.resolve('${var:A}') == 'B=C'
    assert first.execute_command(112, 'var invalid')[0] == 0
    assert first.execute_command(113, 'var a = 133222') == (0, 'Usage: var NAME=VALUE (no spaces around =)')
    assert first.execute_command(114, 'var a= 133222')[0] == 0
    assert first.execute_command(115, 'var a =133222')[0] == 0
    assert first.execute_command(116, 'var a=133222') == (1, 'a set')
    assert first.execute_command(117, 'var') == (1, 'A=B=C\nNEXT=\na=133222')
    assert first.command_variable_resolver.resolve('${var:a}') == '133222'
    assert first.execute_command(118, 'var MESSAGE=hello  world = ok') == (1, 'MESSAGE set')
    assert first.command_variable_resolver.resolve('${var:MESSAGE}') == 'hello  world = ok'
    assert first.execute_command(119, 'var EMPTY=') == (1, 'EMPTY set')
    assert first.command_variable_resolver.resolve('${var:EMPTY}') == ''
    assert first.execute_command(121, 'var a = 99')[0] == 0
    assert first.command_variable_resolver.resolve('${var:a}') == '133222'
    status, output = first.execute_command(120, 'shell echo ${var:a}')
    assert status == 1 and output.strip() == '133222'



def test_linux_getinfo_structured_flat_and_json(monkeypatch):
    from client.commands.runtime.catalog import CommandCatalog
    monkeypatch.setattr(CommandCatalog, '_get_platform_name', lambda _: 'linux')
    executor = CommandExecutor(SimpleNamespace(client_id='one'))
    result = executor.execute_command(201, 'getinfo --json')
    assert result[0] == 1
    data = json.loads(result[1])
    assert list(data) == list(info_module._output_data(data, 'linux', detailed=False))
    assert data['pid'] == os.getpid()
    assert data['ppid'] == os.getppid()
    assert data['mem_total'].endswith((' GB', ' MB', ' TB'))
    assert data['mem_avail'].endswith((' GB', ' MB', ' TB'))
    assert 'os_product' not in data
    assert 'distro_pretty_name' not in data
    assert 'package_manager' not in data and 'has_desktop' not in data
    assert 'default_shell' in data and 'default_shell_ver' in data and 'kernel' in data
    assert 'rch_build_ver' in data and 'rch_build_revision' in data
    assert not any(field in data for field in ('memory_total_gb', 'cpu_cores', 'pretty_name'))
    assert 'gpu_models' not in data
    assert all(not isinstance(value, (dict, list)) for value in data.values())
    full_data = json.loads(executor.execute_command(203, 'getinfo -a --json')[1])
    assert full_data['os_product']
    assert full_data['gpu_models'] is None or isinstance(full_data['gpu_models'], list)
    status, text = executor.execute_command(202, 'getinfo')
    assert status == 1 and 'os_name' in text and '[os]' not in text


def test_linux_getinfo_command_dispatch_json(monkeypatch):
    from client.commands.runtime.catalog import CommandCatalog
    monkeypatch.setattr(CommandCatalog, '_get_platform_name', lambda _: 'linux')
    monkeypatch.setattr(probe_module, 'collect_linux', lambda _, *, detailed: {'kernel': 'test-kernel'})
    monkeypatch.setitem(info_module.COLLECTORS, 'linux', probe_module.collect_linux)
    executor = CommandExecutor(SimpleNamespace(client_id='one'))
    assert ('getinfo', 'system') in {
        (x['name'], x['group']) for x in executor.get_command_manifest_payload()
    }
    data = json.loads(executor.execute_command(201, 'getinfo --json')[1])
    assert data['kernel'] == 'test-kernel'
    assert 'hostname' in executor.execute_command(202, 'getinfo')[1]
    assert executor.execute_command(203, 'getinfo --bad')[0] == 0


def test_missing_linux_files_do_not_break_getinfo(monkeypatch):
    monkeypatch.setattr(probe_module, '_read', lambda _: '')
    data = probe_module.collect_linux(None)
    assert data['cpu_model'] is None
    assert 'os_product' not in data
    assert 'distro_pretty_name' not in data
    assert 'has_desktop' not in data and 'package_manager' not in data
    assert probe_module.collect_linux(None, detailed=True)['os_product'] is None
