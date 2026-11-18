"""Screenshot standalone entry: identical shell contract across macOS and Windows."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.commands.runtime.hosts import MacCommands, WindowsCommands, LinuxCommands, iOSCommands
from client.commands.runtime.catalog import CommandCatalog
from client.commands.shell.common.media import ShellMediaCommands
from client.commands.shell.runner import ShellCommandRunner
from client.commands.shell.standalone import screenshot as module
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


@pytest.mark.parametrize('host', [MacCommands, WindowsCommands])
def test_standalone_is_registered_once_in_common(host):
    assert ShellMediaCommands.__dict__['screenshot'] is module.screenshot
    assert 'screenshot' not in host.__mro__[1].__dict__  # No platform-level mount.
    assert host.screenshot is module.screenshot
    assert host.screenshot.help == 'Capture a screenshot'
    assert host.screenshot.command_output == 'stream'
    assert host.screenshot.command_platforms == ('mac', 'win')
    assert getattr(host.screenshot, 'command_timeout', None) is None


@pytest.mark.parametrize('platform,host', [
    ('mac', MacCommands), ('win', WindowsCommands),
    ('linux', LinuxCommands), ('ios', iOSCommands),
])
def test_common_screenshot_platform_filter_controls_manifest_and_execution(platform, host):
    assert host.screenshot is module.screenshot
    assert 'screenshot' not in host.__mro__[1].__dict__
    catalog = CommandCatalog(Mock())
    catalog._get_platform_name = lambda: platform
    exported = catalog.get_exported_shell_commands()
    assert ('screenshot' in exported) is (platform in ('mac', 'win'))
    entries = {row['name']: row for row in catalog.get_command_manifest_payload()}
    assert ('screenshot' in entries) is (platform in ('mac', 'win'))
    runner = ShellCommandRunner(SimpleNamespace())
    resolved = runner._resolve_builtin_command(host, 'screenshot')
    if platform in ('linux', 'ios'):
        assert resolved() == (0, 'Command not supported on this platform: screenshot')
    else:
        assert resolved is module.screenshot


@pytest.mark.parametrize('os_alias', ['mac', 'win'])
def test_success_has_same_progress_upload_and_cleanup(monkeypatch, tmp_path, os_alias):
    local = tmp_path / 'private_shot.png'
    progress = []
    cleanup = []
    transfer = Mock()
    transfer.upload_single_file_to_server_result.return_value = (1, 'Saved')
    calls = []

    def make_temp(*args, **kwargs):
        assert args == ('media_temp',)
        assert kwargs == {'prefix': 'screenshot_', 'suffix': '.png'}
        return os.open(local, os.O_CREAT | os.O_RDWR), str(local)

    def capture_mac(owner, path):
        calls.append(('mac', path))
        Path(path).write_bytes(b'PNG')

    def capture_win(owner, path):
        calls.append(('win', path))
        Path(path).write_bytes(b'PNG')

    monkeypatch.setattr(module, 'make_client_temp_file', make_temp)
    monkeypatch.setattr(module, 'cleanup_temp_path', lambda path: cleanup.append(path))
    monkeypatch.setattr(module, '_capture_mac', capture_mac)
    monkeypatch.setattr(module, '_capture_win', capture_win)
    owner = SimpleNamespace(
        command_platform=os_alias,
        emit_progress=lambda msg, **kw: progress.append((msg, kw['level'])),
        http_file_transfer_service=transfer,
    )

    assert module.screenshot(owner) == (1, 'Saved')
    assert calls == [(os_alias, str(local))]
    assert progress == [
        (f'Client Temp Path: {local}', 'info'),
        ('Capturing screen...', 'info'),
        ('Screenshot captured successfully', 'success'),
    ]
    upload = transfer.upload_single_file_to_server_result.call_args
    assert upload.args == (str(local),)
    assert upload.kwargs['category'] == 'screenshots'
    assert upload.kwargs['upload_name'].startswith('screenshot_')
    assert upload.kwargs['upload_name'].endswith('.png')
    assert upload.kwargs['extra'] == {'saved_from': 'client_command', 'source_command': 'screenshot'}
    assert cleanup == [str(local)]


@pytest.mark.parametrize('os_alias', ['mac', 'win'])
@pytest.mark.parametrize('status,message', [(0, 'Rejected'), (1, 'Saved')])
def test_upload_result_forwarded_unchanged(monkeypatch, tmp_path, os_alias, status, message):
    path = tmp_path / 'shot.png'
    monkeypatch.setattr(module, 'make_client_temp_file', lambda *_a, **_k: (
        os.open(path, os.O_CREAT | os.O_RDWR), str(path),
    ))
    cleaned = []
    monkeypatch.setattr(module, 'cleanup_temp_path', lambda p: cleaned.append(p))
    monkeypatch.setattr(module, '_capture_mac', lambda *_a: path.write_bytes(b'PNG'))
    monkeypatch.setattr(module, '_capture_win', lambda *_a: path.write_bytes(b'PNG'))
    transfer = Mock()
    transfer.upload_single_file_to_server_result.return_value = (status, message)
    owner = SimpleNamespace(command_platform=os_alias,
                            emit_progress=lambda *_a, **_k: None,
                            http_file_transfer_service=transfer)
    assert module.screenshot(owner) == (status, message)
    assert cleaned == [str(path)]


@pytest.mark.parametrize('os_alias', ['mac', 'win'])
@pytest.mark.parametrize('exc,expected', [
    (RuntimeError('capture failed'), 'Failed to capture screenshot: capture failed'),
    (CommandCancelledError(), 'Screenshot command cancelled'),
    (CommandTimeoutError(), 'Screenshot capture timed out and was terminated'),
])
def test_capture_error_cleans_up_and_never_uploads(monkeypatch, tmp_path, os_alias, exc, expected):
    path = tmp_path / 'shot.png'
    monkeypatch.setattr(module, 'make_client_temp_file', lambda *_a, **_k: (
        os.open(path, os.O_CREAT | os.O_RDWR), str(path),
    ))
    cleaned = []
    monkeypatch.setattr(module, 'cleanup_temp_path', lambda p: cleaned.append(p))

    def failing_capture(*_args):
        raise exc

    monkeypatch.setattr(module, '_capture_mac', failing_capture)
    monkeypatch.setattr(module, '_capture_win', failing_capture)
    transfer = Mock()
    owner = SimpleNamespace(command_platform=os_alias,
                            emit_progress=lambda *_a, **_k: None,
                            http_file_transfer_service=transfer)
    assert module.screenshot(owner) == (0, expected)
    assert cleaned == [str(path)]
    transfer.upload_single_file_to_server_result.assert_not_called()


def test_platform_dispatch_uses_host_identity_not_local_platform(monkeypatch, tmp_path):
    path = tmp_path / 'shot.png'
    monkeypatch.setattr(module, 'make_client_temp_file', lambda *_a, **_k: (
        os.open(path, os.O_CREAT | os.O_RDWR), str(path),
    ))
    monkeypatch.setattr(module, 'cleanup_temp_path', lambda *_a: None)
    calls = []
    monkeypatch.setattr(module, '_capture_mac', lambda *_a: calls.append('mac'))
    monkeypatch.setattr(module, '_capture_win', lambda *_a: calls.append('win'))
    owner = SimpleNamespace(
        command_platform='win',
        emit_progress=lambda *_a, **_k: None,
        http_file_transfer_service=Mock(
            upload_single_file_to_server_result=Mock(return_value=(1, 'Saved')),
        ),
    )
    assert module.screenshot(owner) == (1, 'Saved')
    assert calls == ['win']


def test_mac_uses_managed_capture_and_quoted_temp_path(tmp_path):
    path = str(tmp_path / 'shot with space.png')
    calls = []
    owner = SimpleNamespace(process_execution_service=SimpleNamespace(run_shell_command=lambda command: (
        calls.append(command) or SimpleNamespace(returncode=0, stderr='')
    )))
    module._capture_mac(owner, path)
    assert calls == [f"screencapture -x '{path}'"]


def test_mac_capture_reports_nonzero_exit():
    owner = SimpleNamespace(process_execution_service=SimpleNamespace(run_shell_command=lambda command: SimpleNamespace(
        returncode=1, stderr='Screen recording denied',
    )))
    with pytest.raises(RuntimeError, match='Screen recording denied'):
        module._capture_mac(owner, '/tmp/shot.png')


def test_win_capture_imports_native_dependency_only_when_called(monkeypatch, tmp_path):
    class Image:
        def save(self, path):
            Path(path).write_bytes(b'PNG')

    monkeypatch.setitem(sys.modules, 'pyautogui', SimpleNamespace(screenshot=lambda: Image()))
    path = tmp_path / 'shot.png'
    module._capture_win(SimpleNamespace(), str(path))
    assert path.read_bytes() == b'PNG'
