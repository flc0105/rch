"""Client launch, elevation, pause and update handoff."""

import base64
import ctypes
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.app.client import Client
from client.commands.shell.common import maintenance as update_ops
from client.commands.shell.common.maintenance import ShellMaintenanceCommands
from client.commands.shell.standalone import _elevated_win as elevated
from client.commands.shell.standalone import run_elevated
from client.commands.shell.standalone import spawn_elevated_instance as instance


@pytest.mark.parametrize('platform', ['mac', 'win'])
def test_modes_dispatch_without_interpreting_direct_arguments(monkeypatch, platform):
    owner = SimpleNamespace(command_platform=platform, _checkpoint=lambda: None)
    adapter_type = run_elevated._ADAPTERS[platform]
    shell = Mock(return_value=(1, 'ok'))
    collect = Mock(return_value=(1, 'collected'))
    detached = Mock(return_value=(1, 'started'))
    opened = Mock(return_value=(1, 'opened'))
    console = Mock(return_value=(1, 'console'))
    monkeypatch.setattr(adapter_type, 'shell', shell)
    monkeypatch.setattr(adapter_type, 'collect', collect)
    monkeypatch.setattr(adapter_type, 'detached', detached)
    if platform == 'win':
        monkeypatch.setattr(adapter_type, 'open', opened)
        monkeypatch.setattr(adapter_type, 'show_console', console)

    command = 'echo "quoted value" | text'
    assert run_elevated.run_elevated(owner, '--no-confirm ' + command) == (1, 'ok')
    assert run_elevated.run_elevated(owner, '--no-confirm --shell ' + command) == (1, 'ok')
    assert [call.args for call in shell.call_args_list] == [(command,), (command,)]
    assert run_elevated.run_elevated(owner, '--no-confirm --collect -- ' + command + ' --no-confirm') == (
        1, 'collected',
    )
    collect.assert_called_once_with(command + ' --no-confirm')

    program = r'C:\Program Files\Client.exe' if platform == 'win' else '/tmp/Client binary'
    assert run_elevated.run_elevated(owner, f'--no-confirm --detached -- "{program}" "x y" |') == (1, 'started')
    detached.assert_called_once_with([program, 'x y', '|'])

    open_result = run_elevated.run_elevated(owner, f'--no-confirm --open "{program}"')
    console_result = run_elevated.run_elevated(owner, '--no-confirm --show-console ' + command)
    if platform == 'win':
        assert open_result == (1, 'opened')
        assert console_result == (1, 'console')
        opened.assert_called_once_with([program])
        console.assert_called_once_with(command)
    else:
        for status, message in (open_result, console_result):
            assert status == 0 and 'only available on Windows' in message

    for arguments in ('--shell --open echo', '--collect --detached echo', '--collect', '--shell --'):
        assert run_elevated.run_elevated(owner, '--no-confirm ' + arguments)[0] == 0
    assert run_elevated.run_elevated(owner, '--no-confirm --native echo')[0] == 0


@pytest.mark.parametrize(('shell_status', 'report', 'expected_status', 'text'), [
    (42, {'ok': True, 'pid': 12345}, 1, 'PID: 12345'),
    (42, {'ok': False, 'error': 'Client failed to launch'}, 0, 'Client failed to launch'),
    (42, None, 0, 'did not return a launch result'),
    (5, None, 0, 'ShellExecuteW: 5'),
])
def test_spawn_windows_waits_for_original_status_file(monkeypatch, tmp_path, shell_status, report,
                                                      expected_status, text):
    def shell_execute(hwnd, verb, executable, parameters, cwd, show):
        assert hwnd is None and verb == 'runas' and show == 0
        assert cwd == os.getcwd()
        assert executable
        request = json.loads(base64.b64decode(parameters.rsplit(' ', 1)[-1]))
        status_path = Path(request['status_path'])
        assert status_path.parent.parent == tmp_path
        assert status_path.name == 'launch-status.json'
        assert request['log_path'] == str(status_path.with_name('spawn.log'))
        if report is not None:
            status_path.write_text(json.dumps(report), encoding='utf-8')
        return shell_status

    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(
        shell32=SimpleNamespace(ShellExecuteW=shell_execute)), raising=False)
    monkeypatch.setattr('client.runtime.temp_workspace.get_temp_category_dir', lambda *a, **k: str(tmp_path))
    if shell_status > 32 and report is None:
        monkeypatch.setattr(instance, '_DETACHED_RESULT_TIMEOUT_SECONDS', 0)

    result, message = instance._spawn_elevated_win()
    assert result == expected_status and text in message
    if shell_status <= 32:
        assert list(tmp_path.iterdir()) == []
    else:
        assert 'Startup log:' in message


@pytest.mark.parametrize('mode', ['shell', 'collect'])
def test_windows_shell_worker_reports_output_and_nonzero_status(monkeypatch, mode):
    from io import BytesIO

    pending = [b'first\r\n', b'stderr\r\n']
    pipe = BytesIO()
    monkeypatch.setattr(pipe, 'fileno', lambda: 42)
    spawn = Mock(return_value=SimpleNamespace(
        pid=456, stdout=pipe, poll=lambda: None if pending else 7,
    ))
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(get_osfhandle=lambda fd: fd))
    monkeypatch.setattr(elevated, '_windows_system_directory', lambda: r'C:\Windows\System32')
    monkeypatch.setattr(elevated, 'os', SimpleNamespace(
        getcwd=elevated.os.getcwd, path=__import__('ntpath'), name='posix',
        read=lambda _fd, _length: pending.pop(0),
    ))

    def peek(_pipe, _buffer, _length, _read, available, _left):
        available._obj.value = len(pending[0]) if pending else 0
        return True

    monkeypatch.setattr(ctypes, 'WinDLL', lambda *_a, **_kw: SimpleNamespace(
        PeekNamedPipe=Mock(side_effect=peek)), raising=False)
    threads = []

    @contextmanager
    def launch(payload, _cwd):
        thread = threading.Thread(target=elevated.run_windows_helper, args=(payload,))
        threads.append(thread)
        thread.start()
        yield lambda: None

    monkeypatch.setattr(elevated, '_launch_helper', launch)
    owner = SimpleNamespace(_checkpoint=lambda: None, emit_chunk=Mock())
    command = '"C:\\With Space\\tool.exe" "quoted arg" | findstr "test"'
    try:
        adapter = elevated.WindowsElevation(owner)
        result = getattr(adapter, mode)(command)
    finally:
        for thread in threads:
            thread.join(timeout=2)
    assert spawn.call_args.args == (
        r'C:\Windows\System32\cmd.exe' + ' /d /s /c "' + command + '"',
    )
    assert spawn.call_args.kwargs['creationflags'] == 0x08000000
    assert spawn.call_args.kwargs['stderr'] == subprocess.STDOUT
    if mode == 'collect':
        assert result == (0, 'first\nstderr\nElevated command exited with code 7')
        owner.emit_chunk.assert_not_called()
    else:
        assert result == (0, 'Elevated command exited with code 7')
        assert [call.args[0] for call in owner.emit_chunk.call_args_list] == ['first', 'stderr']


class _Connection:
    def __init__(self, events):
        self.events = events

    def report_session_end(self, reason, *, command=''):
        self.events.append(('report', reason, command))
        return True

    def close(self):
        self.events.append(('close',))


@pytest.mark.parametrize('platform', ['nt', 'posix'])
def test_update_close_waits_for_protocol_reporting_before_closing(monkeypatch, platform):
    events = []
    host = SimpleNamespace(socket=_Connection(events))
    monkeypatch.setattr(update_ops.os, 'name', platform)

    ShellMaintenanceCommands._close_update_connection(host)

    assert events == [
        ('report', 'client_update', 'update'),
        ('close',),
    ]


def test_pause_result_is_sent_before_socket_is_closed():
    client = Client.__new__(Client)
    client.server = Mock()
    client.receiver_worker = Mock()
    client.receiver_worker.receive_idle_seconds.return_value = None
    client.receiver_worker.pop_error.return_value = None
    client.server.recv_command.side_effect = [(99, 1, 'paused'), SystemExit()]
    client.server.consume_pause_request.return_value = True
    client.connection_lifecycle = Mock()
    client.connection_lifecycle.is_paused = False
    client.local_ipc = Mock()
    records = []
    client.connect = lambda: records.append('connect')
    client.server.send_result.side_effect = lambda *args: records.append('result')
    client.server.report_session_end.side_effect = lambda *args, **kw: records.append(('end', args, kw))
    client.connection_lifecycle.pause.side_effect = lambda: records.append('pause')
    client._wait_for_commands()
    assert records == ['result', ('end', ('client_paused',), {'command': 'pause_connection'}), 'pause', 'connect']
