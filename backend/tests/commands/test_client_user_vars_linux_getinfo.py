"""Client-scoped var namespace and Linux system information command."""
import json
import os
from types import SimpleNamespace

from client.commands.runtime.command_variable_resolver import (
    CommandVariableResolver, CommandVariableResolutionError,
)
from client.commands.runtime.executor import CommandExecutor
from client.commands.platform.linux import LinuxCommands
from client.commands.platform.services.linux.system_service import LinuxSystemService
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
    service = LinuxSystemService(None)
    monkeypatch.setattr(service, '_os_release', lambda: {
        'NAME': 'Ubuntu', 'VERSION': '22.04', 'PRETTY_NAME': 'Ubuntu 22.04 LTS'
    })
    monkeypatch.setattr(service, '_memory', lambda: (2.0, 1.5, .5))
    monkeypatch.setattr(service, '_gpu', lambda: 'Sample GPU')
    monkeypatch.setattr(service, '_route_ip', lambda: '10.1.2.3')
    monkeypatch.setattr(service, '_read', lambda _: '')
    result = service.collect_system_info()
    assert result.status == 1 and result.shape == 'dict'
    assert result.data['memory_total_gb'] == 2.0
    assert result.data['distro'] == 'Ubuntu'
    assert result.data['ip'] == '10.1.2.3'
    expected_fields = {
        'distro', 'os_version', 'pretty_name', 'kernel', 'arch', 'hostname', 'host',
        'cpu_model', 'cpu_cores', 'memory_total_gb', 'memory_used_gb',
        'memory_available_gb', 'gpu', 'ip', 'python_version', 'python_executable',
        'package_manager', 'default_shell', 'current_shell', 'has_desktop',
        'resolution', 'user', 'is_root', 'cwd', 'pid', 'ppid', 'process_name',
        'cmdline', 'exe',
    }
    assert set(result.data) == expected_fields
    assert result.data['pid'] == os.getpid()
    assert result.data['ppid'] == os.getppid()
    assert all(not isinstance(value, (dict, list)) for value in result.data.values())
    status, raw = render_structured_result(result, output_format='json')
    assert status == 1 and json.loads(raw) == result.data
    status, text = render_structured_result(result)
    assert status == 1 and 'distro' in text and '[os]' not in text


def test_linux_getinfo_command_dispatch_json(monkeypatch):
    from client.commands.runtime.catalog import CommandCatalog
    monkeypatch.setattr(CommandCatalog, '_get_platform_name', lambda _: 'linux')
    monkeypatch.setattr(LinuxSystemService, 'collect_system_info', lambda _: 
                        __import__('core.utils.command_output', fromlist=['StructuredCommandResult'])
                        .StructuredCommandResult(status=1, data={'hostname': 'alpha', 'cpu_cores': 2}, shape='dict', width=24))
    executor = CommandExecutor(SimpleNamespace(client_id='one'))
    assert ('getinfo', 'system') in {
        (x['name'], x['group']) for x in executor.get_commands().get_command_manifest_payload()
    }
    assert json.loads(executor.execute_command(201, 'getinfo --json')[1]) == {'hostname': 'alpha', 'cpu_cores': 2}
    assert 'hostname' in executor.execute_command(202, 'getinfo')[1]
    assert executor.execute_command(203, 'getinfo --bad')[0] == 0


def test_memory_when_linux_meminfo_missing(monkeypatch):
    service = LinuxSystemService(None)
    monkeypatch.setattr(service, '_read', lambda _: '')
    assert service._memory() == (None, None, None)
