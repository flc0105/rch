"""Exercise the Windows worker and native launcher bindings without a UAC prompt."""

from contextlib import contextmanager
import base64
import ctypes
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.commands.shell.standalone import _elevated_win as elevated
from client.commands.shell.standalone._elevated_process import ElevationCancelled, run_authorized_process
from client.commands.shell.standalone import spawn_elevated_instance as instance
from core.utils.local_process_channel import read_frame


@pytest.mark.parametrize('startup_check', [False, True])
def test_windows_worker_reports_direct_child_pid(monkeypatch, tmp_path, startup_check):
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
    log = str(tmp_path / 'start.log') if startup_check else None
    try:
        result = run_authorized_process(
            owner, 'win', 'detached', arguments, startup_log=log,
            clear_env=['RCH_PROCESS_RECOVERY_WATCHDOG_SESSION'],
        )
    finally:
        for thread in threads:
            thread.join(timeout=2)
    assert result == (1, 'Elevated process started (PID: 12345)')
    assert spawn.call_args.args == (arguments,)
    assert spawn.call_args.kwargs['creationflags'] == 0x208
    assert spawn.call_args.kwargs['stdin'] == subprocess.DEVNULL
    if startup_check:
        assert Path(log).is_file()
        assert 'RCH_PROCESS_RECOVERY_WATCHDOG_SESSION' not in spawn.call_args.kwargs['env']
    else:
        assert spawn.call_args.kwargs['stderr'] == subprocess.DEVNULL


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


def test_spawn_windows_cancellation_removes_unused_log(monkeypatch, tmp_path):
    def cancelled(*args, **kwargs):
        raise ElevationCancelled('UAC cancelled')

    monkeypatch.setattr(instance, 'run_authorized_process', cancelled)
    monkeypatch.setattr('client.runtime.temp_workspace.get_temp_category_dir', lambda *a, **k: str(tmp_path))
    assert instance._spawn_elevated_win(object()) == (0, 'UAC cancelled')
    assert list(tmp_path.iterdir()) == []


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
