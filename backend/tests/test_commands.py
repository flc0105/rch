"""Command routing, typed arguments and platform availability."""

import json
import os
import sqlite3
from contextlib import closing
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.acmd.runner import ArgumentCommandRunner
from client.commands.runtime.catalog import CommandCatalog
from client.commands.runtime.hosts import iOSCommands, LinuxCommands, MacCommands, WindowsCommands
from client.runtime.command_variable_resolver import CommandVariableResolver
from client.runtime.execution.process.process_service import ProcessService
from client.runtime.execution.request import ExecutionRequest
from server.application.command import alias_manager
from server.application.command.command_planner import CommandPlanner
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


def invocation(name, text):
    return SERVER_COMMAND_REGISTRY.parse_invocation(name, text)


def test_job_repeated_params_support_spaces_and_embedded_flag_as_value():
    data = invocation('job', 'start demo --json -- --greeting "hello  world" '
                             '--literal=--json')
    assert data.output_format == 'json'
    assert data.arguments['params'] == {'greeting': 'hello  world', 'literal': '--json'}


def test_config_windows_path_remains_literal():
    parsed = SERVER_COMMAND_REGISTRY.parse_invocation('config',
        r'set --key SCRIPT_PYTHON_PATH --value "C:\Program Files\Python312\python.exe"',
        literal_backslashes=True)
    assert parsed.arguments['value'] == r'C:\Program Files\Python312\python.exe'


def _handler_with_stubs():
    from server.application.command.builtin_command_handler import BuiltinCommandHandler
    handler = BuiltinCommandHandler.__new__(BuiltinCommandHandler)
    from types import SimpleNamespace
    handler.conn = SimpleNamespace(session_info=SimpleNamespace(os_alias="mac"))
    calls = []
    for spec in SERVER_COMMAND_REGISTRY._commands.values():
        def record(self, *args, command_name=spec.name):
            calls.append((command_name, args))
            return iter([(1, 'ok')])
        setattr(handler, spec.handler, MethodType(record, handler))
    return handler, calls


def test_unknown_builtin_is_not_claimed_and_unknown_subcommand_is_error():
    handler, calls = _handler_with_stubs()
    assert handler.resolve_builtin_command('not-a-builtin', 'xyz') is None
    status, _ = next(iter(handler.resolve_builtin_command('xt', 'bad')))
    assert status == 0
    assert not calls


class AcmdExecutor:
    def __init__(self, registry):
        self.command_variable_resolver = CommandVariableResolver(SimpleNamespace())
        self.registry = registry
        self.invocations = 0

    def get_argument_command_registry(self):
        self.invocations += 1
        return self.registry

    def execute_bound_request(self, request, callback):
        return callback(None)


def parsed(command):
    return CommandPlanner.__new__(CommandPlanner).parse_argument_command(command)


def test_acmd_resolves_pid_before_integer_validation(monkeypatch):
    pid = os.getpid()
    monkeypatch.setattr(ProcessService, 'list_processes', lambda self: [
        {'pid': pid, 'ppid': 1, 'name': 'python', 'username': 'demo', 'status': 'running'},
    ])
    executor = AcmdExecutor(ArgumentCommandRegistry(LinuxCommands(socket=SimpleNamespace())))
    runner = ArgumentCommandRunner(executor)
    request = ExecutionRequest(command_id=12)

    for command in ('acmd ps --pid ${rch:pid} --json',
                    'acmd ps --pid=${rch:pid} --json',
                    'acmd ps ${rch:pid} --json'):
        payload = parsed(command)
        status, result = runner.execute(request, payload)
        assert status == 1, result
        assert str(pid) in result
        assert '${rch:pid}' in str(payload), 'ACMD input payload must not be mutated'


HOSTS = [MacCommands, WindowsCommands, LinuxCommands, iOSCommands]


COMMON = {'sqlite_query', 'image_info', 'python_packages', 'archive_peek', 'find', 'wget', 'download', 'file_shred', 'wait_pid', 'tcp_check'}


IOS_ONLY = {'alert', 'tree', 'head', 'tail'}


LOCAL_UI = {'msgbox', 'notify', 'clipboard_read', 'clipboard_write'}


def make_host(host_type=LinuxCommands):
    return host_type(socket=SimpleNamespace(send_event=Mock()))


def execute(host, text):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return ArgumentCommandRegistry(host).execute(payload)


@pytest.mark.parametrize('host_type', HOSTS)
def test_capabilities(host_type, monkeypatch):
    host = make_host(host_type)
    registry = ArgumentCommandRegistry(host)
    entries = {item['name'] for item in registry.list_command_entries()}
    assert COMMON <= entries
    assert IOS_ONLY & entries == (IOS_ONLY if host.command_platform == 'ios' else set())
    assert LOCAL_UI & entries == (LOCAL_UI if host.command_platform != 'linux' else set())
    catalog = CommandCatalog(host.socket)
    catalog.platform_commands = host
    monkeypatch.setattr(catalog, '_get_platform_name', lambda: host.command_platform)
    names = [item['name'] for item in catalog.get_command_manifest_payload()]
    assert len(names) == len(set(names))
    assert not {'download', 'clipboard_read', 'clipboard_write', 'file_shred'} & set(names)
    assert 'uptime' in names
    for command in COMMON | IOS_ONLY | LOCAL_UI:
        assert (f'acmd {command}' in names) == (command in entries)

    assert ('launchd' in entries) == (host.command_platform == 'mac')


def test_sqlite_limit_applies_to_both_outputs_without_a_default_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with closing(sqlite3.connect('sample.db')) as conn:
        conn.execute('CREATE TABLE items (name)')
        conn.executemany('INSERT INTO items VALUES (?)', [(f'ROW_{idx:03d}',) for idx in range(120)])
        conn.commit()
    host = make_host()
    query = 'acmd sqlite_query --db sample.db --query "SELECT name FROM items ORDER BY name"'
    assert 'ROW_119' in execute(host, query)[1]
    assert 'ROW_002' not in execute(host, query + ' --limit 2')[1]
    status, output = execute(host, query + ' --json --limit 2')
    assert status == 1 and json.loads(output) == [{'name': 'ROW_000'}, {'name': 'ROW_001'}]
    assert execute(host, query + ' --limit 0')[0] == 0
    delete = 'acmd sqlite_query --db sample.db --query "DELETE FROM items"'
    assert execute(host, delete)[0] == 0
    with closing(sqlite3.connect('sample.db')) as conn:
        assert conn.execute('SELECT COUNT(*) FROM items').fetchone() == (120,)


def test_windows_alias_preserves_quoted_paths(tmp_path, monkeypatch):
    aliases = tmp_path / 'aliases.json'
    aliases.write_text(json.dumps({'win': {'open': 'read-file "<path>"'}}), encoding='utf-8')
    monkeypatch.setattr(alias_manager, 'ALIAS_PATH', str(aliases))
    manager = alias_manager.AliasManager()
    conn = SimpleNamespace(session_info=SimpleNamespace(os_alias='win'))
    path = r'C:\Users\测试用户\My Logs\agent.log'
    for args in (f'"{path}"', f'--path "{path}"'):
        resolved = manager.resolve_alias('open', args=args, conn=conn)
        assert resolved['platform'] == 'win'
        assert resolved['command'] == f'read-file "{path}"'


def test_ios_tree_filters_files_and_keeps_nested_directories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'docs' / 'archive').mkdir(parents=True)
    (tmp_path / 'docs' / 'notes.txt').touch()
    (tmp_path / 'top.txt').touch()
    host = make_host(iOSCommands)

    status, normal = execute(host, 'acmd tree .')
    assert status == 1 and 'notes.txt' in normal and 'top.txt' in normal
    for flag in ('--dirs-only', '-d'):
        status, output = execute(host, f'acmd tree . {flag}')
        assert status == 1 and 'docs/' in output and 'archive/' in output
        assert 'notes.txt' not in output and 'top.txt' not in output
