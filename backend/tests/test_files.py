"""File safety, conflict handling, clipboard and transfers."""

import os
import ssl
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call
from urllib.error import URLError

import pytest

from client.clipboard.manager import ClipboardManager
from client.commands.acmd.common import files as file_commands
from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.shell.standalone import _cleanup_plan as cleanup
from client.commands.runtime.executor import CommandExecutor
from client.commands.runtime.catalog import CommandCatalog
from client.runtime.execution.context import CommandCancelledError
from client.runtime.execution.interaction_service import CommandInteractions
from client.runtime.filesystem.conflict_policy import apply_path, commit_download_file
from server.application.command.command_planner import CommandPlanner


def run(text, host='linux'):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return make_host(host)._test_catalog.get_argument_command_registry().execute(payload)


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


def make_host(host_type='linux'):
    catalog = CommandCatalog(SimpleNamespace(send_event=Mock()))
    catalog._get_platform_name = lambda: host_type
    context = catalog.get_commands()
    context._test_catalog = catalog
    return context


def execute(host, text):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(text)
    return host._test_catalog.get_argument_command_registry().execute(payload)


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
        str(path), category='downloads', upload_name='renamed file.zip', managed=True,
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


@pytest.mark.parametrize('host_type', ['mac', 'win'])
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
    assert execute(host, 'acmd clipboard_write hello world')[0] == 1
    assert execute(host, 'acmd clipboard_write --text "hello   world"')[0] == 1
    assert execute(host, 'acmd clipboard_write --text hello world')[0] == 0
    assert adapter.set_text.call_args_list == [call('hello world'), call('hello   world')]

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
    status, listing = execute(host, 'acmd clipboard_read')
    assert status == 1 and listing.splitlines()[1:] == ['single.txt']
    transfer.upload_single_file_to_server_result.assert_not_called()
    assert execute(host, 'acmd clipboard_read --download') == (1, '')
    transfer.upload_single_file_to_server_result.assert_called_once_with(
        str(item), category='clipboard', extra={'saved_from': 'clipboard'}, managed=True,
    )
    for paths in ([str(folder)], [str(item), str(folder)]):
        adapter.get_snapshot.return_value['paths'] = paths
        assert execute(host, 'acmd clipboard_read --download') == (1, '')
        transfer.upload_paths_as_zip_to_server_result.assert_called_with(
            paths, category='clipboard', extra={'saved_from': 'clipboard'}, managed=True,
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
        'tree_signature': service._snapshot(str(outsider))[0],
    }]
    result = service.execute_plan(plan, {'preview_temp'})
    assert result['removed_files'] == 0
    assert outsider.read_text() == 'must stay'
    assert result['items'][0]['skipped_paths']


def test_cleanup_counts_each_release_once_and_reports_partial_deletion(tmp_path, monkeypatch):
    current, old, staging = [tmp_path / path for path in ('current', 'old', 'new.extracting.123')]
    for directory in (current, old, staging):
        directory.mkdir()
        (directory / 'rchclient.py').write_text('entry')
    (old / 'locked.txt').write_text('keep on simulated failure')

    monkeypatch.setattr(cleanup, 'get_client_bundle_release_dir', lambda: str(tmp_path))
    monkeypatch.setattr(cleanup.sys, 'argv', [str(current / 'rchclient.py')])
    service = cleanup.ClientCleanupService()
    service.ITEMS = ('bundle_old_releases', 'bundle_extracting_residue')
    plan = service.plan()
    old_item, staging_item = plan['items']
    assert [entry['path'] for entry in old_item['paths']] == [str(old)]
    assert [entry['path'] for entry in staging_item['paths']] == [str(staging)]
    assert current.exists() and old.exists() and staging.exists()

    def partial_delete(path):
        (Path(path) / 'rchclient.py').unlink()
        raise PermissionError('simulated busy file')

    with monkeypatch.context() as context:
        context.setattr(cleanup.shutil, 'rmtree', partial_delete)
        result = service.execute_plan(plan, {'bundle_old_releases'})
    assert result['error_count'] == 1 and result['removed_files'] == 1 and result['removed_dirs'] == 0
    assert current.exists() and staging.exists() and (old / 'locked.txt').exists()

    (staging / 'rchclient.py').write_text('changed after preview')
    result = service.execute_plan(plan, {'bundle_extracting_residue'})
    assert result['removed_dirs'] == 0 and staging.exists()
    assert 'changed after preview' in result['items'][0]['skipped_paths'][0]


@pytest.mark.parametrize('option', ['', ' --no-confirm'])
def test_clean_continues_after_an_unreadable_release(tmp_path, monkeypatch, option):
    releases = tmp_path / 'releases'
    downloads = tmp_path / 'downloads'
    blocked = releases / 'a-blocked' / 'private'
    removable = releases / 'z-old'
    for directory in (blocked, removable, downloads):
        directory.mkdir(parents=True)
    archive = downloads / 'rchclient_python_clean_test.zip'
    archive.write_bytes(b'old download')
    monkeypatch.setattr(cleanup.ClientCleanupService, 'ITEMS', ('bundle_old_releases', 'bundle_archive_residue'))
    monkeypatch.setattr(cleanup, 'get_client_bundle_release_dir', lambda: str(releases))
    monkeypatch.setattr(cleanup, 'get_client_bundle_download_dir', lambda: str(downloads))
    scandir = os.scandir

    def scan_directory(path):
        if str(path) == str(blocked):
            raise PermissionError(13, 'Permission denied', str(path))
        return scandir(path)

    monkeypatch.setattr(os, 'scandir', scan_directory)
    previews = []

    def preview(_self, _message, plan, **_kwargs):
        previews.append(plan)
        assert blocked.exists() and removable.exists() and archive.exists()
        return plan['row_ids']

    monkeypatch.setattr(CommandInteractions, 'select_preview_rows', preview)
    events = Mock()
    command = CommandExecutor(SimpleNamespace(send_event=events))
    status, result = command.execute_command(1, 'clean' + option)

    assert (status, result['status']) == (1, 'partial')
    assert '1 scan error(s)' in result['message']
    assert blocked.exists() and not removable.exists() and not archive.exists()
    assert len(previews) == (1 if not option else 0)
    if previews:
        release_row = previews[0]['rows'][0]
        assert release_row['category'] == 'bundle_old_releases' and release_row['directories'] == '1'
    messages = [call.args[1]['message'] for call in events.call_args_list]
    assert f'Failed to scan bundle_old_releases: {blocked}: Permission denied' in messages
    assert not any(text.startswith('Failed to delete:') for text in messages)


def test_wget_combines_ca_sources_and_preserves_target_if_verify_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / 'report.txt'
    target.write_bytes(b'previous')
    bundle = tmp_path / 'public.pem'
    bundle.touch()
    local_bundle = tmp_path / 'private.pem'
    monkeypatch.setitem(sys.modules, 'certifi', SimpleNamespace(where=lambda: str(bundle)))
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', str(local_bundle))
    context = Mock()
    create_context = Mock(return_value=context)
    monkeypatch.setattr(ssl, 'create_default_context', create_context)
    failure = ssl.SSLCertVerificationError('could not get local issuer')
    failure.verify_message = 'could not get local issuer'
    connect = Mock(side_effect=URLError(failure))
    monkeypatch.setattr(file_commands, 'urlopen', connect)

    status, _ = execute(make_host(), 'acmd wget https://example.invalid -o report.txt')
    assert status == 0
    create_context.assert_called_once_with()
    assert context.load_verify_locations.call_args_list == [
        call(cafile=str(bundle)), call(cafile=str(local_bundle)),
    ]
    assert context.method_calls == [call.load_verify_locations(cafile=str(bundle)),
                                    call.load_verify_locations(cafile=str(local_bundle))]
    assert connect.call_args.kwargs['context'] is context
    assert target.read_bytes() == b'previous'


def test_file_shred_overwrites_exact_requested_passes_and_removes_only_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sample = tmp_path / 'sample.txt'
    sample.write_bytes(b'abc')
    recorded = []

    def fsync(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        recorded.append(os.read(fd, 3))

    monkeypatch.setattr(file_commands.os, 'fsync', fsync)
    host = make_host()
    assert execute(host, 'acmd file_shred sample.txt --passes 0')[0] == 0
    assert sample.read_bytes() == b'abc'
    assert execute(host, 'acmd file_shred .')[0] == 0

    assert execute(host, 'acmd file_shred sample.txt --passes 2')[0] == 1
    assert recorded == [bytes(3), bytes([255]) * 3]
    assert not sample.exists()
