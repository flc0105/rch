"""Isolated checks of the elevated Python helper and UAC status reporting."""

import base64
import ctypes
import json
import subprocess
import sys
from types import SimpleNamespace

from client.commands.platform.services.win.privilege_service import (
    _ELEVATED_DETACHED_HELPER, WinPrivilegeService,
)


def _execute_helper(monkeypatch, tmp_path, popen):
    payload = {
        'argv': [r'C:\Python 3\python.exe', r'C:\中文 目录\rchclient.py', '--profile', 'tls-local'],
        'cwd': r'C:\RCH Files',
        'status_path': str(tmp_path / 'status.json'),
        'log_path': str(tmp_path / 'stderr.log'),
        'clear_env': ['RCH_PROCESS_RECOVERY_WATCHDOG_SESSION'],
    }
    monkeypatch.setattr(subprocess, 'Popen', popen)
    monkeypatch.setattr(subprocess, 'DETACHED_PROCESS', 0x8, raising=False)
    monkeypatch.setattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, raising=False)
    monkeypatch.setattr(sys, 'argv', ['-c', base64.b64encode(json.dumps(payload).encode()).decode()])
    monkeypatch.setattr('time.sleep', lambda _: None)
    monkeypatch.setenv('RCH_PROCESS_RECOVERY_WATCHDOG_SESSION', 'stale')
    exec(_ELEVATED_DETACHED_HELPER, {'__name__': '__main__'})
    return json.loads((tmp_path / 'status.json').read_text(encoding='utf-8'))


def test_python_helper_starts_detached_process_and_cleans_watchdog_env(monkeypatch, tmp_path):
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(pid=12346, poll=lambda: None)

    status = _execute_helper(monkeypatch, tmp_path, fake_popen)
    assert status == {'ok': True, 'pid': 12346}
    argv, kwargs = calls[0]
    assert argv[1] == r'C:\中文 目录\rchclient.py'
    assert argv[-2:] == ['--profile', 'tls-local']
    assert kwargs['creationflags'] == 0x208
    assert kwargs['shell'] is False
    assert kwargs['cwd'] == r'C:\RCH Files'
    assert 'RCH_PROCESS_RECOVERY_WATCHDOG_SESSION' not in kwargs['env']


def test_python_helper_returns_create_process_error(monkeypatch, tmp_path):
    def fake_popen(*args, **kwargs):
        raise OSError('CreateProcess failed: access denied')

    status = _execute_helper(monkeypatch, tmp_path, fake_popen)
    assert status == {'ok': False, 'error': 'CreateProcess failed: access denied'}
    assert 'access denied' in (tmp_path / 'stderr.log').read_text(encoding='utf-8')


def test_windows_detached_elevation_returns_failure_on_helper_error(monkeypatch, tmp_path):
    def shell_execute(*args):
        path = next(tmp_path.glob('client_elevation_*')) / 'launch-status.json'
        path.write_text(json.dumps({'ok': False, 'error': 'CreateProcess failed: 5'}))
        return 42

    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(
        shell32=SimpleNamespace(ShellExecuteW=shell_execute)), raising=False)
    monkeypatch.setattr('client.runtime.temp_workspace.get_temp_category_dir', lambda *a, **k: str(tmp_path))
    status, message = WinPrivilegeService(None).spawn_elevated_instance(detached=True)
    assert status == 0
    assert 'CreateProcess failed: 5' in message
    assert 'Startup log:' in message


def test_windows_detached_elevation_rejected_uac_cleans_request_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(
        shell32=SimpleNamespace(ShellExecuteW=lambda *args: 5)), raising=False)
    monkeypatch.setattr('client.runtime.temp_workspace.get_temp_category_dir', lambda *a, **k: str(tmp_path))
    status, message = WinPrivilegeService(None).spawn_elevated_instance(detached=True)
    assert status == 0
    assert 'ShellExecuteW: 5' in message
    assert list(tmp_path.iterdir()) == []


def test_windows_detached_elevation_timeout_reports_missing_helper_status(monkeypatch, tmp_path):
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(
        shell32=SimpleNamespace(ShellExecuteW=lambda *args: 42)), raising=False)
    monkeypatch.setattr('client.runtime.temp_workspace.get_temp_category_dir', lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(WinPrivilegeService, 'DETACHED_RESULT_TIMEOUT_SECONDS', 0.001)
    status, message = WinPrivilegeService(None).spawn_elevated_instance(detached=True)
    assert status == 0
    assert 'did not return a launch result' in message


def test_python_helper_rejects_immediately_exited_client(monkeypatch, tmp_path):
    def fake_popen(*args, **kwargs):
        return SimpleNamespace(pid=23345, poll=lambda: 1)

    status = _execute_helper(monkeypatch, tmp_path, fake_popen)
    assert status['ok'] is False
    assert 'exited immediately with code: 1' in status['error']


def test_windows_non_detached_elevation_retains_original_command(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(
        shell32=SimpleNamespace(ShellExecuteW=lambda *args: calls.append(args) or 42)), raising=False)
    monkeypatch.setattr('client.runtime.client_util.get_exec_and_args', lambda: ('python.exe', '"rchclient.py" --profile tls-local'))
    result = WinPrivilegeService(None).spawn_elevated_instance(detached=False)
    assert result == (1, 'Elevated Client launch requested')
    assert len(calls) == 1
    assert calls[0][:4] == (None, 'runas', 'python.exe', '"rchclient.py" --profile tls-local')
    assert calls[0][5] == 1
