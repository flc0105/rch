"""Detached command: real executable PID, session and cleanup behavior."""

import os
import shlex
import sys
import time
from types import SimpleNamespace

import pytest

from client.commands.common.mixins.execution_ops import CommandExecutionMixin
from client.commands.common.services.process.process_execution_service import ProcessExecutionService
from client.commands.platform.ios import iOSCommands


def test_detached_command_registered_and_ios_hidden():
    assert getattr(CommandExecutionMixin.run_detached, 'help', '')
    assert not hasattr(iOSCommands.run_detached, 'help')


def test_usage_and_failed_start():
    obj = CommandExecutionMixin()
    assert obj.run_detached('') == (0, 'Usage: run_detached <program> [args...]')
    status, result = obj.run_detached('not-a-real-rch-executable-name-9999')
    assert status == 0 and 'Failed to start detached process:' in result


@pytest.mark.skipif(os.name == 'nt', reason='POSIX session test')
def test_spawn_direct_program_pid_and_new_session(tmp_path):
    process_service = ProcessExecutionService(SimpleNamespace())
    pid_file = tmp_path / 'actual_pid.txt'
    snippet = 'import os,sys,time; open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(1)'
    command = f'{shlex.quote(sys.executable)} -c {shlex.quote(snippet)} {shlex.quote(str(pid_file))}'
    child = process_service.spawn_detached_program(command)
    try:
        for _ in range(500):
            if pid_file.exists():
                break
            time.sleep(.01)
        assert pid_file.exists()
        assert int(pid_file.read_text()) == child.pid
        assert os.getsid(child.pid) == child.pid
    finally:
        child.wait(timeout=3)
    assert child.returncode == 0


@pytest.mark.skipif(os.name == 'nt', reason='POSIX executable resolution test')
def test_bare_filename_runs_directly_and_argument_is_literal(tmp_path, monkeypatch):
    script = tmp_path / 'my program'
    marker = tmp_path / 'literal.txt'
    script.write_text(f'#!{sys.executable}\nimport sys,pathlib\npathlib.Path(sys.argv[2]).write_text(sys.argv[1])\n')
    script.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    cmd = f'"my program" "literal;&&" {shlex.quote(str(marker))}'
    child = ProcessExecutionService(SimpleNamespace()).spawn_detached_program(cmd)
    child.wait(timeout=3)
    assert child.returncode == 0
    assert marker.read_text() == 'literal;&&'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX background shell reaping test')
def test_bgrun_shell_pid_is_reaped():
    proc = ProcessExecutionService(SimpleNamespace()).spawn_background_process('exit 0')
    for _ in range(300):
        if proc.returncode is not None:
            break
        time.sleep(.01)
    assert proc.returncode == 0  # The background reaper, not the test, called wait().


def test_windows_process_creation_uses_detached_flags(monkeypatch):
    import client.commands.common.services.process.process_execution_service as module
    from types import SimpleNamespace

    creation_flags = 0x8 | 0x200
    fake_os = SimpleNamespace(name='nt', path=os.path, getcwd=os.getcwd)
    monkeypatch.setattr(module, 'os', fake_os)
    monkeypatch.setattr(module.subprocess, 'DETACHED_PROCESS', 0x8, raising=False)
    monkeypatch.setattr(module.subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, raising=False)
    captured = {}
    fake_process = SimpleNamespace(pid=5555)

    def fake_popen(argv, **kwargs):
        captured['argv'], captured['kwargs'] = argv, kwargs
        return fake_process

    monkeypatch.setattr(module.subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(module.ProcessExecutionService, '_reap_independent_process', staticmethod(lambda process: None))
    service = module.ProcessExecutionService(SimpleNamespace())
    process = service.spawn_detached_program(r'"C:\Program Files\tool.exe" --path "C:\data\a b.txt"')
    assert process.pid == 5555
    assert captured['argv'] == [r'C:\Program Files\tool.exe', '--path', r'C:\data\a b.txt']
    assert captured['kwargs']['creationflags'] == creation_flags
    assert captured['kwargs']['close_fds'] is True
    assert captured['kwargs']['stdin'] == module.subprocess.DEVNULL
