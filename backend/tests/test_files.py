"""File safety, conflict handling, clipboard and transfers."""

import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.clipboard.manager import ClipboardManager
from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.common.services import client_cleanup_service as cleanup
from client.commands.runtime.hosts import LinuxCommands, MacCommands, WindowsCommands
from client.runtime.execution.context import CommandCancelledError
from client.runtime.filesystem.conflict_policy import apply_path, commit_download_file
from server.application.command.command_planner import CommandPlanner


def run(text, host=LinuxCommands):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return ArgumentCommandRegistry(host(socket=SimpleNamespace(send_event=lambda *_args, **_kwargs: None))).execute(payload)


def test_unzip_blocks_zip_slip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with zipfile.ZipFile(tmp_path / 'evil.zip', 'w') as archive:
        archive.writestr('../outside.txt', 'unsafe')
    status, body = run('acmd unzip evil.zip')
    assert status == 0
    assert not (tmp_path / 'outside.txt').exists()
    assert not (tmp_path.parent / 'outside.txt').exists()


def test_merge_nested_type_collision_leaves_original_tree(tmp_path):
    source, target = tmp_path / 'src', tmp_path / 'dst'
    source.mkdir()
    target.mkdir()
    (source / 'same').write_text('new')
    (target / 'same').mkdir()
    (source / 'alpha').write_text('alpha')
    with pytest.raises(FileExistsError):
        apply_path(str(source), str(target), 'copy', 'merge')
    assert list(target.iterdir()) == [target / 'same']
    assert (target / 'same').is_dir()


def test_upload_commit_existing_file_and_directory(tmp_path):
    original = tmp_path / 'data.txt'
    incoming = tmp_path / 'staged'
    original.write_text('original')
    incoming.write_text('new')
    with pytest.raises(FileExistsError):
        commit_download_file(str(incoming), str(original), 'stop')
    assert original.read_text() == 'original' and incoming.exists()

    kept = commit_download_file(str(incoming), str(original), 'keep_both')
    assert original.read_text() == 'original' and Path(kept).read_text() == 'new'
    incoming.write_text('replacement')
    commit_download_file(str(incoming), str(original), 'replace')
    assert original.read_text() == 'replacement'

    folder = tmp_path / 'folder'
    folder.mkdir()
    incoming.write_text('file')
    with pytest.raises(FileExistsError):
        commit_download_file(str(incoming), str(folder), 'replace')
    assert folder.is_dir() and incoming.exists()


def make_host(host_type=LinuxCommands):
    return host_type(socket=SimpleNamespace(send_event=Mock()))


def execute(host, text):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return ArgumentCommandRegistry(host).execute(payload)


@pytest.fixture
def endpoint():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/redirect':
                self.send_response(302)
                self.send_header('Location', '/file?token=demo')
                self.end_headers()
                return
            if self.path == '/missing':
                self.send_error(404)
                return
            data = b'a' * 1024
            self.send_response(200)
            if self.path != '/unknown.bin':
                self.send_header('Content-Length', str(len(data) + (8 if self.path == '/truncated' else 0)))
            if self.path.startswith('/file?'):
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''report%20name.bin")
            self.end_headers()
            self.wfile.write(data)

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


def test_wget_http_error_short_read_and_cancellation_leave_target(tmp_path, endpoint, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host = make_host()
    target = tmp_path / 'preserved.bin'
    target.write_bytes(b'previous')
    for path, expected in [('missing', 'HTTP 404'), ('truncated', 'incomplete')]:
        status, output = execute(host, f'acmd wget {endpoint}/{path} -o preserved.bin')
        assert status == 0 and expected in output
        assert target.read_bytes() == b'previous'
        assert not list(tmp_path.glob('.rch-wget-*.part'))

    checkpoint = Mock(side_effect=[None, None, CommandCancelledError('cancelled')])
    monkeypatch.setattr(host, '_checkpoint', checkpoint)
    with pytest.raises(CommandCancelledError):
        execute(host, f'acmd wget {endpoint}/unknown.bin -o preserved.bin')
    assert target.read_bytes() == b'previous'
    assert not list(tmp_path.glob('.rch-wget-*.part'))
    assert execute(host, 'acmd wget file:///sample -o preserved.bin')[0] == 0


def test_download_uses_existing_upload_and_optional_artifact_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'report #1.zip'
    path.write_bytes(b'payload')
    host = make_host()
    transfer = Mock()
    transfer.upload_single_file_to_server_result.return_value = (1, '')
    host._http_file_transfer_service = transfer

    assert execute(host, 'acmd download "report #1.zip" --name "renamed file.zip"') == (1, '')
    transfer.upload_single_file_to_server_result.assert_called_once_with(
        str(path), category='downloads', upload_name='renamed file.zip',
        extra={'saved_from': 'client_command', 'source_command': 'acmd download "report #1.zip" --name "renamed file.zip"'},
    )
    assert execute(host, 'acmd download --path "report #1.zip"')[0] == 1
    assert transfer.upload_single_file_to_server_result.call_args.kwargs['upload_name'] == ''
    assert execute(host, 'acmd download')[0] == 0
    assert execute(host, 'acmd download .')[0] == 0
    assert execute(host, 'acmd download "report #1.zip" --name ../other.zip')[0] == 0
    assert path.read_bytes() == b'payload'


def test_wget_conflict_modes(tmp_path, monkeypatch, endpoint):
    monkeypatch.chdir(tmp_path)
    host = make_host()
    target = tmp_path / 'existing.bin'
    target.write_bytes(b'old')
    command = f'acmd wget {endpoint}/unknown.bin -o existing.bin'
    assert execute(host, command + ' --conflict stop')[0] == 0
    assert target.read_bytes() == b'old'
    status, output = execute(host, command + ' --conflict keep_both')
    renamed = Path(output.splitlines()[-1])
    assert status == 1 and renamed != target and renamed.read_bytes() == b'a' * 1024
    assert target.read_bytes() == b'old'
    assert execute(host, command + ' --conflict replace')[0] == 1
    assert target.read_bytes() == b'a' * 1024
    assert execute(host, command + ' --conflict unknown')[0] == 0
    assert not list(tmp_path.glob('.rch-wget-*.part'))


def clipboard_manager(host, tmp_path, adapter):
    manager = ClipboardManager.__new__(ClipboardManager)
    manager._operation_lock = threading.RLock()
    manager.staging_dir = str(tmp_path)
    manager.adapter = adapter
    host.socket.runtime = SimpleNamespace(clipboard_manager=manager)
    return manager


@pytest.mark.parametrize('host_type', [MacCommands, WindowsCommands])
def test_clipboard_acmd_reuses_desktop_snapshot_and_artifact_flows(host_type, tmp_path):
    host = make_host(host_type)
    adapter = Mock()
    manager = clipboard_manager(host, tmp_path, adapter)
    transfer = Mock()
    transfer.upload_single_file_to_server_result.return_value = (1, '')
    transfer.upload_paths_as_zip_to_server_result.return_value = (1, '')
    host._http_file_transfer_service = transfer
    manager._upload_bytes_artifact = Mock(return_value={'original_name': 'clipboard_sample.png'})

    adapter.get_snapshot.return_value = {'kind': 'text', 'text': 'read me'}
    assert execute(host, 'acmd clipboard_read') == (1, 'read me')
    assert execute(host, 'acmd clipboard_write --text "hello world"') == (1, 'Clipboard updated')
    adapter.set_text.assert_called_once_with('hello world')

    adapter.get_snapshot.return_value = {'kind': 'image', 'data': b'png', 'format': 'png'}
    assert execute(host, 'acmd clipboard_read') == (1, 'Clipboard contains an image')
    manager._upload_bytes_artifact.assert_not_called()
    assert 'clipboard_sample.png' in execute(host, 'acmd clipboard_read --download')[1]
    assert manager._upload_bytes_artifact.call_args.kwargs['category'] == 'clipboard'

    item = tmp_path / 'single.txt'
    item.touch()
    folder = tmp_path / 'folder'
    folder.mkdir()
    adapter.get_snapshot.return_value = {'kind': 'files', 'paths': [str(item)]}
    assert execute(host, 'acmd clipboard_read')[0] == 1
    transfer.upload_single_file_to_server_result.assert_not_called()
    assert execute(host, 'acmd clipboard_read --download') == (1, '')
    transfer.upload_single_file_to_server_result.assert_called_once_with(
        str(item), category='clipboard', extra={'saved_from': 'clipboard'},
    )
    for paths in ([str(folder)], [str(item), str(folder)]):
        adapter.get_snapshot.return_value['paths'] = paths
        assert execute(host, 'acmd clipboard_read --download') == (1, '')
        transfer.upload_paths_as_zip_to_server_result.assert_called_with(
            paths, category='clipboard', extra={'saved_from': 'clipboard'},
        )


@pytest.fixture
def managed(tmp_path, monkeypatch):
    root = tmp_path / 'rch_client_temp'
    root.mkdir()
    monkeypatch.setattr(cleanup, 'get_client_temp_root', lambda create=False: str(root))
    monkeypatch.setattr(cleanup, 'get_temp_category_dir', lambda category, create=False: str(root / category))
    monkeypatch.setattr(cleanup, 'get_client_log_path', lambda: '')
    return root


def test_cleanup_rejects_modified_plan_with_unowned_path(managed):
    outsider = managed.parent / 'outside.log'
    outsider.write_text('must stay')
    service = cleanup.ClientCleanupService()
    service.ITEMS = ('preview_temp',)
    plan = service.plan()
    plan['items'][0]['paths'] = [{
        'path': str(outsider),
        'identity': service._candidate_identity(str(outsider)),
        'tree_signature': service._tree_signature(str(outsider)),
    }]
    result = service.execute_plan(plan, {'preview_temp'})
    assert result['removed_files'] == 0
    assert outsider.read_text() == 'must stay'
    assert result['items'][0]['skipped_paths']
