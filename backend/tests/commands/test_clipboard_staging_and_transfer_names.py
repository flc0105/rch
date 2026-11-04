"""Clipboard staging ownership and Unicode transfer name regressions."""
import os
from pathlib import Path
from types import SimpleNamespace

from client.clipboard import manager as clipboard_manager
from client.clipboard.adapters.windows import WindowsClipboardAdapter, _PACKAGED_FILE_CLIPBOARD_HELPER_SOURCE
from server.application.execution.upload_execution_service import UploadExecutionService


def test_client_reconnect_does_not_erase_clipboard_staging(monkeypatch, tmp_path):
    staging = tmp_path / 'clipboard_staging'
    existing = staging / 'other-request' / 'Oracle 按银行账号 自动挂接.txt'
    existing.parent.mkdir(parents=True)
    existing.write_text('keep me', encoding='utf-8')
    monkeypatch.setattr(clipboard_manager, 'get_local_identity', lambda: SimpleNamespace(os_alias='win'))
    monkeypatch.setattr(clipboard_manager, 'get_temp_category_dir', lambda *a, **kw: str(staging))
    monkeypatch.setattr(clipboard_manager.ClipboardManager, '_build_adapter', lambda self: SimpleNamespace())
    instance = clipboard_manager.ClipboardManager(SimpleNamespace())
    assert instance.staging_dir == str(staging)
    assert existing.read_text(encoding='utf-8') == 'keep me'


def test_unicode_transfer_name_reaches_client_without_temp_ascii_name(tmp_path):
    source = tmp_path / 'temp-safe-name.txt'
    source.write_bytes(b'contents')
    sent = []
    created = []
    session = SimpleNamespace(session_info=SimpleNamespace(client_id='client-1', hostname='test'), send=sent.append)

    artifact = SimpleNamespace(
        stage_local_file=lambda path, display_name='': (str(source), 'temp-safe-name.txt'),
        build_upload_temp_download_relative_url=lambda path: '/api/upload-tmp/safe/temp-safe-name.txt',
        cleanup_upload_temp_file=lambda path: None,
    )
    transfer = SimpleNamespace(
        create_transfer=lambda **kw: created.append(kw) or {'transfer_id':'transfer-1'},
        wait_for_terminal=lambda tid: {'state': 'completed'},
    )
    service = UploadExecutionService(None, SimpleNamespace(get_connection=lambda target: session), artifact, transfer)
    filename = 'Oracle 按银行账号 自动挂接回单附件.txt'
    events = list(service.iter_upload_events('client-1', str(source), display_name=filename,
                                            use_transfer_manager=True, build_http_receive_command=lambda payload: 'unused'))
    assert sent[0]['payload']['filename'] == filename
    assert created[0]['filename'] == filename
    assert sent[0]['payload']['relative_url'].endswith('/temp-safe-name.txt')
    assert events[-1].event_type == 'completed'


def test_unicode_clipboard_paths_are_not_ascii_encoded():
    # The helper owns CF_HDROP memory; both embedded and source helpers must
    # return 64-bit Windows HANDLE values without ctypes' default int truncation.
    helper_file = Path(clipboard_manager.__file__).parent / 'windows_file_clipboard_helper.py'
    helper_source = helper_file.read_text(encoding='utf-8')
    for source in (helper_source, _PACKAGED_FILE_CLIPBOARD_HELPER_SOURCE):
        assert "('\\x00'.join(paths) + '\\x00\\x00').encode('utf-16le')" in source
        for field in ('GlobalAlloc', 'GlobalLock', 'GlobalFree'):
            assert f'kernel32.{field}.restype = ctypes.c_void_p' in source
        assert 'user32.SetClipboardData.restype = ctypes.c_void_p' in source
    assert WindowsClipboardAdapter().get_capabilities()['files'] is True


def test_windows_clipboard_helper_receives_unicode_paths_as_separate_argv(monkeypatch, tmp_path):
    from client.clipboard.adapters import windows as win_clipboard
    filename = 'Oracle 按银行账号 自动挂接回单附件.txt'
    path = tmp_path / filename
    path.write_text('receipt', encoding='utf-8')
    adapter = WindowsClipboardAdapter()
    monkeypatch.setattr(adapter, '_prepare_file_clipboard_helper',
                        lambda: (['python.exe'], r'C:\RCH\clipboard_helper.py', False))
    calls = []
    monkeypatch.setattr(win_clipboard.subprocess, 'run',
                        lambda argv, **kwargs: calls.append((argv, kwargs)) or
                        SimpleNamespace(returncode=0, stderr='', stdout=''))
    adapter.set_files([str(path)])
    assert calls[0][0][-1] == str(path)
    assert calls[0][0][0] == 'python.exe'
    assert calls[0][1]['check'] is False
