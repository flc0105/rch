"""Exercise the Windows worker and native launcher bindings without a UAC prompt."""

from contextlib import contextmanager
import base64
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.commands.shell.standalone import _elevated_win as elevated
from client.commands.shell.standalone._elevated_process import ElevationCancelled
from client.commands.shell.standalone import spawn_elevated_instance as instance
from core.utils.local_process_channel import read_frame


def test_windows_worker_reports_direct_child_pid(monkeypatch):
    spawn = Mock(return_value=SimpleNamespace(pid=12345, poll=lambda: None))
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    monkeypatch.setattr(subprocess, 'DETACHED_PROCESS', 8, raising=False)
    monkeypatch.setattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, raising=False)
    monkeypatch.setenv('RCH_PROCESS_RECOVERY_WATCHDOG_SESSION', 'stale')

    threads = []

    @contextmanager
    def launch(payload, _cwd):
        thread = threading.Thread(target=elevated.run_windows_helper, args=(payload,))
        threads.append(thread)
        thread.start()
        yield lambda: None

    monkeypatch.setattr(elevated, '_launch_helper', launch)
    owner = SimpleNamespace(_checkpoint=lambda: None)
    arguments = [r'C:\Program Files\Python\python.exe', 'with spaces', '--profile', 'tls-local']
    try:
        result = elevated.WindowsElevation(owner).detached(arguments)
    finally:
        for thread in threads:
            thread.join(timeout=2)
    assert result == (1, 'Elevated process started (PID: 12345)')
    assert spawn.call_args.args == (arguments,)
    assert spawn.call_args.kwargs['creationflags'] == 0x208
    assert spawn.call_args.kwargs['stdin'] == subprocess.DEVNULL
    assert spawn.call_args.kwargs['stdout'] == subprocess.DEVNULL
    assert spawn.call_args.kwargs['stderr'] == subprocess.DEVNULL
    assert spawn.call_args.kwargs['env']['RCH_PROCESS_RECOVERY_WATCHDOG_SESSION'] == 'stale'


def test_windows_launch_runs_the_command_script_in_isolated_python(monkeypatch, tmp_path):
    worker = str(Path(elevated.__file__).resolve())
    monkeypatch.setenv('PYTHONPATH', str(tmp_path))

    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(5)
        request = {
            'port': listener.getsockname()[1], 'token': 'token', 'ack': 'yes',
            'cwd': str(tmp_path), 'mode': 'detached', 'command': ['not-started.exe'],
        }
        payload = base64.b64encode(json.dumps(request).encode()).decode()
        child_args = ['-I', worker, payload]

        @contextmanager
        def launch(executable, arguments, cwd, *, show):
            assert executable == sys.executable
            assert arguments == subprocess.list2cmdline(child_args)
            assert cwd == str(tmp_path) and show == 0
            with subprocess.Popen([executable, *child_args], cwd=cwd, stderr=subprocess.PIPE) as child:
                yield SimpleNamespace(WaitForSingleObject=Mock(return_value=258)), child.pid
                assert child.wait(timeout=5) == 1
                assert child.stderr.read() == b''

        monkeypatch.setattr(elevated, '_windows_launch', launch)
        with elevated._launch_helper(payload, request['cwd']):
            peer, _ = listener.accept()
            with peer:
                peer.settimeout(5)
                assert read_frame(peer, lambda: None) == (b'T', b'token')
                # Decline the handshake so the real script exits before
                # trying to create a Windows-only target process.
                peer.sendall(b'no!')


def test_windows_open_uses_runas_real_handle_and_closes_it(monkeypatch):
    def execute(pointer):
        options = ctypes.cast(pointer, ctypes.POINTER(elevated._ShellExecuteInfo)).contents
        assert options.lpVerb == 'runas'
        assert options.lpFile == r'C:\Program Files\Edit.exe'
        assert options.lpParameters == '"argument with spaces"'
        assert options.nShow == 1
        options.hProcess = 123
        return 1

    native = {
        'shell32': SimpleNamespace(ShellExecuteExW=Mock(side_effect=execute)),
        'kernel32': SimpleNamespace(GetProcessId=Mock(return_value=246),
                                    CloseHandle=Mock(return_value=1)),
    }
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, **_kwargs: native[name], raising=False)
    assert elevated.WindowsElevation(None).open([r'C:\Program Files\Edit.exe', 'argument with spaces']) == (
        1, 'Opened elevated program (PID: 246)'
    )
    native['kernel32'].CloseHandle.assert_called_once_with(123)


@pytest.mark.parametrize(('exit_code', 'create_error'), [
    (None, None),
    (7, None),
    (None, 'CreateProcess failed'),
])
def test_spawn_windows_reports_status_from_detached_helper(monkeypatch, tmp_path, exit_code, create_error):
    status_path = tmp_path / 'launch-status.json'
    log_path = tmp_path / 'spawn.log'
    argv = [r'C:\Program Files\Python\python.exe', r'C:\RCH Directory\rchclient.py', '--profile', 'tls-local']
    request = {
        'argv': argv, 'cwd': str(tmp_path), 'status_path': str(status_path), 'log_path': str(log_path),
        'clear_env': ['RCH_PROCESS_RECOVERY_WATCHDOG_SESSION'],
    }
    payload = base64.b64encode(json.dumps(request).encode('utf-8')).decode('ascii')
    spawn = Mock(
        return_value=SimpleNamespace(pid=12346, poll=lambda: exit_code),
        side_effect=OSError(create_error) if create_error else None,
    )
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    monkeypatch.setattr(subprocess, 'DETACHED_PROCESS', 8, raising=False)
    monkeypatch.setattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, raising=False)
    monkeypatch.setenv('RCH_PROCESS_RECOVERY_WATCHDOG_SESSION', 'stale')

    with monkeypatch.context() as process:
        process.setattr(sys, 'argv', ['-c', payload])
        process.setattr('time.sleep', lambda _: None)
        exec(instance._ELEVATED_DETACHED_HELPER, {'__name__': '__main__'})

    report = json.loads(status_path.read_text(encoding='utf-8'))
    assert not status_path.with_suffix('.json.tmp').exists()
    assert spawn.call_args.args == (argv,)
    assert spawn.call_args.kwargs['cwd'] == str(tmp_path)
    assert spawn.call_args.kwargs['creationflags'] == 0x208
    assert spawn.call_args.kwargs['shell'] is False
    assert spawn.call_args.kwargs['stdin'] == subprocess.DEVNULL
    assert spawn.call_args.kwargs['stdout'] == subprocess.DEVNULL
    assert 'RCH_PROCESS_RECOVERY_WATCHDOG_SESSION' not in spawn.call_args.kwargs['env']
    if create_error or exit_code is not None:
        error = create_error or f'Client exited immediately with code: {exit_code}'
        assert report == {'ok': False, 'error': error}
        assert error in log_path.read_text(encoding='utf-8')
    else:
        assert report == {'ok': True, 'pid': 12346}


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


def test_windows_show_console_delegates_raw_command_to_visible_elevated_cmd(monkeypatch):
    execute = Mock(return_value=33)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *_a, **_kw: SimpleNamespace(ShellExecuteW=execute), raising=False)
    command = 'echo "two words" & pause'

    assert elevated.WindowsElevation(None).show_console(command) == (1, f'Executed: {command}')
    execute.assert_called_once_with(None, 'runas', 'cmd.exe', f'/c {command}', None, 1)


@pytest.mark.parametrize('error', [5, 1223])
def test_windows_show_console_handles_launch_failure_and_cancel(monkeypatch, error):
    execute = Mock(return_value=5)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *_a, **_kw: SimpleNamespace(ShellExecuteW=execute), raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: error, raising=False)
    adapter = elevated.WindowsElevation(None)
    if error == 1223:
        with pytest.raises(ElevationCancelled, match='UAC authorization cancelled'):
            adapter.show_console('whoami')
    else:
        assert adapter.show_console('whoami') == (0, 'Failed to open elevated console (Windows Shell error 5)')
