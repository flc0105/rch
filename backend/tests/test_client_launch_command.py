"""Self-launch commands have one canonical argv source across Client paths."""

import base64
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from client.runtime import client_util
from client.commands.shell.common import session as session_ops
from client.watchdog import process_recovery_watchdog
from client.watchdog.watchdog_process import ClientWatchdogProcess
from client.commands.platform.services.win.privilege_service import WinPrivilegeService
from client.commands.platform.services.mac.system_service import MacSystemService


@pytest.mark.parametrize('frozen', [False, True])
def test_argv_source_and_shell_command_preserve_runtime_profile(monkeypatch, frozen):
    executable = '/tmp/Python Interpreter/python3'
    script = '/tmp/project with spaces/rchclient.py'
    monkeypatch.setattr(client_util.sys, 'executable', executable)
    monkeypatch.setattr(client_util.sys, 'argv', [script, '--profile', 'tls local', '--flag=x&y'])
    if frozen:
        monkeypatch.setattr(client_util.sys, 'frozen', True, raising=False)
    else:
        monkeypatch.delattr(client_util.sys, 'frozen', raising=False)

    prefix = [os.path.realpath(executable)] + ([] if frozen else [os.path.realpath(script)])
    expected = [*prefix, '--profile', 'tls local', '--flag=x&y']
    assert client_util.get_executable_argv() == expected
    assert client_util.get_executable_argv(include_runtime_args=False) == prefix
    if client_util.os.name == 'posix':
        import shlex
        assert shlex.split(client_util.get_executable_path()) == expected

    exe, params = client_util.get_exec_and_args()
    assert exe == expected[0]
    assert params == subprocess.list2cmdline(expected[1:])
    assert process_recovery_watchdog._launch_argv() == expected
    assert process_recovery_watchdog._worker_command('s', 1, 2, expected, '/tmp')[:len(prefix)] == prefix

    process = ClientWatchdogProcess.__new__(ClientWatchdogProcess)
    process.client_id = 'device'
    process.remote_control_watchdog_enabled = False
    process.remote_control_watchdog_base_url = ''
    process.remote_control_watchdog_interval_seconds = 1
    process.remote_control_watchdog_log_file_path = ''
    process.local_heartbeat_watchdog_enabled = False
    process.local_heartbeat_watchdog_timeout_seconds = 1
    process.local_heartbeat_watchdog_heartbeat_file_path = ''
    process.local_heartbeat_watchdog_log_file_path = ''
    assert process._build_parent_launch_argv() == expected
    worker = process._build_worker_argv()
    assert worker[:len(prefix)] == prefix
    assert '--profile' not in worker[:worker.index('--watchdog-worker')]
    assert json.loads(worker[worker.index('--watch-parent-launch-argv-json') + 1]) == expected


@pytest.mark.parametrize('frozen', [False, True])
def test_spawn_instance_uses_shared_argv_and_keeps_detached(monkeypatch, frozen):
    monkeypatch.setattr(client_util.sys, 'executable', '/tmp/py binary')
    monkeypatch.setattr(client_util.sys, 'argv', ['/tmp/rchclient.py', '--profile', 'tls-local'])
    if frozen:
        monkeypatch.setattr(client_util.sys, 'frozen', True, raising=False)
    else:
        monkeypatch.delattr(client_util.sys, 'frozen', raising=False)

    captured = {}
    monkeypatch.setattr(client_util.subprocess, 'Popen', lambda command, **kw: captured.update(command=command, kw=kw) or SimpleNamespace(pid=321))
    process = session_ops._spawn_instance()
    assert process.pid == 321
    assert captured['command'] == client_util.get_executable_argv()
    if client_util.os.name == 'posix':
        assert captured['kw']['start_new_session'] is True
    assert captured['kw']['shell'] is False
    assert 'RCH_CLIENT_LAUNCH_MODE' not in captured['kw']['env']


def test_reexec_instance_uses_shared_argv_without_string_reparse(monkeypatch):
    monkeypatch.setattr(session_ops, 'get_executable_argv', lambda: ['/tmp/python with spaces', '/tmp/client.py', '--profile', 'tls-local'])
    monkeypatch.setattr(session_ops, 'get_runtime_root', lambda: '/tmp')
    seen = {}
    monkeypatch.setattr(client_util.os, 'execv', lambda executable, argv: seen.update(executable=executable, argv=argv))
    monkeypatch.setattr(client_util.os, 'chdir', lambda _: None)
    socket = SimpleNamespace(report_session_end=lambda *a, **kw: None, close=lambda: None)
    session_ops._reexec_instance(socket)
    assert seen == {
        'executable': '/tmp/python with spaces',
        'argv': ['/tmp/python with spaces', '/tmp/client.py', '--profile', 'tls-local'],
    }


def test_windows_elevation_detached_uses_same_argv(monkeypatch):
    target = ['C:\\Program Files\\Python\\python.exe', 'C:\\RCH Directory\\rchclient.py', '--profile', 'tls-local']
    monkeypatch.setattr(client_util, 'get_executable_argv', lambda **kw: list(target))
    exe, ps_args = WinPrivilegeService._detached_launch_arguments()
    assert exe.lower().endswith('powershell.exe')
    encoded = ps_args.rsplit(' ', 1)[-1]
    script = base64.b64decode(encoded).decode('utf-16-le')
    assert 'CreateProcessW' in script
    assert '0x208' in script
    assert '--profile tls-local' in script
    assert 'C:\\RCH Directory\\rchclient.py' in script


def test_macos_getinfo_uses_canonical_launch_command(monkeypatch):
    from client.commands.shell.standalone import getinfo as info
    identity = SimpleNamespace(os_alias='mac', os_name='macOS', os_version='15.1',
                               arch='arm64', manufacturer='Apple', model='MacBook Pro',
                               hostname='test-host')
    monkeypatch.setattr(info, 'get_local_identity', lambda: identity)
    monkeypatch.setattr(info, 'get_executable_path', lambda: 'python client.py --profile tls-local')
    monkeypatch.setitem(info.COLLECTORS, 'mac', lambda owner: {'kernel': 'Darwin'})
    owner = SimpleNamespace(_checkpoint=lambda: None)
    result = info.getinfo(owner)
    assert result.data['launch_command'] == 'python client.py --profile tls-local'
    assert result.data['os_name'] == 'macOS'


def test_windows_shell_command_is_rendered_from_the_shared_argv(monkeypatch):
    argv = [r'C:\Program Files\Python\python.exe', r'C:\RCH Files\rchclient.py', '--profile', 'tls-local']
    monkeypatch.setattr(client_util, 'get_executable_argv', lambda **kw: list(argv))
    monkeypatch.setattr(client_util, 'os', SimpleNamespace(name='nt'))
    assert client_util.get_executable_path() == subprocess.list2cmdline(argv)


def test_session_commands_delegate_to_matching_module_functions(monkeypatch):
    from client.commands.shell.common.session import ShellSessionCommands

    socket = object()
    owner = ShellSessionCommands()
    owner.socket = socket
    calls = []
    monkeypatch.setattr(session_ops, '_relaunch_instance',
                        lambda connection: calls.append(('relaunch', connection)))
    monkeypatch.setattr(session_ops, '_reexec_instance',
                        lambda connection: calls.append(('reexec', connection)))
    monkeypatch.setattr(session_ops, '_spawn_instance',
                        lambda: calls.append(('spawn', None)) or SimpleNamespace(pid=2468))

    assert owner.relaunch_instance('--no-confirm') is None
    assert owner.reexec_instance() is None
    assert owner.spawn_instance() == (1, 'New client instance started, pid=2468')
    assert calls == [('relaunch', socket), ('reexec', socket), ('spawn', None)]


def test_obsolete_client_util_lifecycle_entrypoints_are_removed():
    for name in ('reset', 'reexec_restart', 'spawn_new_instance', '_spawn_new_instance_process'):
        assert not hasattr(client_util, name)
