"""File clipboard contract regression: native adapters, Client, Server, and Web."""

import json
from types import SimpleNamespace

import pytest

from client.clipboard.manager import ClipboardManager
from server.application.web.clipboard_api import WebClipboardApi


def make_client_manager(platform='win', *, files=True, snapshot=None):
    manager = ClipboardManager.__new__(ClipboardManager)
    manager._os_alias = platform
    manager.adapter = SimpleNamespace(
        get_capabilities=lambda: {'text': True, 'image': True, 'files': files},
        get_snapshot=lambda: snapshot or {'kind': 'empty'},
    )
    return manager


@pytest.mark.parametrize('platform', ['win', 'mac'])
def test_desktop_client_reports_file_capability(platform):
    manager = make_client_manager(platform)
    assert manager.get_capabilities() == {
        'text': True,
        'image': True,
        'files': True,
    }


def test_file_capability_false_is_preserved():
    assert make_client_manager('ios', files=False).get_capabilities()['files'] is False


def test_file_snapshot_is_returned_with_documented_shape(tmp_path):
    file_path = tmp_path / '财务 文件.txt'
    file_path.write_bytes(b'contents')
    folder = tmp_path / 'folder'
    folder.mkdir()
    manager = make_client_manager(snapshot={
        'kind': 'files',
        'paths': [str(file_path), str(folder), str(tmp_path / 'gone.txt')],
    })
    payload = manager._materialize_snapshot(manager.adapter.get_snapshot())
    assert payload['kind'] == 'files'
    assert len(payload['files']) == 2
    assert payload['files'][0] == {
        'path': str(file_path),
        'name': '财务 文件.txt',
        'size': 8,
        'is_directory': False,
    }
    assert payload['files'][1]['is_directory'] is True
    assert payload['files'][1]['size'] == 0


def test_client_get_returns_files_to_web(tmp_path):
    file_path = tmp_path / 'note.txt'
    file_path.write_text('hello', encoding='utf-8')
    manager = make_client_manager(snapshot={'kind': 'files', 'paths': [str(file_path)]})
    status, payload = manager.get_clipboard('content')
    assert status == 1
    assert payload['kind'] == 'files'
    assert payload['files'][0]['name'] == 'note.txt'
    assert 'capabilities' not in payload
    capabilities_status, capabilities = manager.get_clipboard('capabilities')
    assert capabilities_status == 1 and capabilities['capabilities']['files'] is True


def test_client_set_files_dispatches_to_native_adapter(tmp_path):
    manager = make_client_manager()
    manager.staging_dir = str(tmp_path)
    root = tmp_path / 'received'
    root.mkdir()
    native_calls = []
    manager.adapter.set_files = lambda paths: native_calls.append(paths)
    manager._download_staged_items = lambda request_id, items, *, roots, checkpoint: [str(root)]
    status, payload = manager.set_clipboard('request-2', {
        'kind': 'files',
        'items': [{'type': 'directory', 'path': 'received'}],
        'roots': ['received'],
    })
    assert native_calls == [[str(root)]]
    assert status == 1
    assert payload == {'kind': 'files'}


def test_legacy_saved_clipboard_kind_is_not_accepted(tmp_path):
    manager = make_client_manager()
    manager.staging_dir = str(tmp_path)
    status, result = manager.set_clipboard('request-old', {'kind': 'saved', 'items': [], 'roots': []})
    assert status == 0
    assert 'Unsupported clipboard payload' in result


class FakeClipboardSession:
    def __init__(self, *, files=True):
        self.files = files
        self.sent = []

    def get_capabilities(self, client_id):
        return {'capabilities': {'platform': 'win', 'files': self.files}}

    def set_clipboard(self, client_id, payload, *, action, arguments=None):
        self.sent.append((client_id, payload))
        self.action = action
        self.arguments = arguments
        return {'ok': True}


class FakeArtifactStore:
    def __init__(self, file_path, *, artifact_type='shared'):
        self.file_path = str(file_path)
        self.artifact_type = artifact_type
        self.cleaned = []

    def get_artifact_by_id(self, artifact_id):
        return {'artifact_type': self.artifact_type, 'original_name': '报表.txt'}

    def get_artifact_file_path(self, artifact_id):
        return self.file_path

    def stage_local_file(self, file_path, display_name):
        assert file_path == self.file_path
        assert display_name == '报表.txt'
        return self.file_path, '报表.txt'

    def build_upload_temp_download_relative_url(self, file_path):
        return '/api/temporary/report'

    def cleanup_upload_temp_file(self, path):
        self.cleaned.append(path)


def test_artifact_send_uses_files_protocol_and_cleans_stage(tmp_path):
    file_path = tmp_path / 'blob_without_extension'
    file_path.write_bytes(b'file data')
    session = FakeClipboardSession(files=True)
    artifacts = FakeArtifactStore(file_path)
    api = WebClipboardApi(session, artifacts)
    assert api.set_artifact_file('win-client', 'artifact-1') == {'ok': True}
    assert session.sent == [('win-client', {
        'kind': 'files',
        'items': [{'type': 'file', 'path': '报表.txt', 'name': '报表.txt',
                   'url': '/api/temporary/report'}],
        'roots': ['报表.txt'],
    })]
    assert session.action == 'set_artifact_file'
    assert session.arguments == {'count': 1, 'names': ['报表.txt'], 'names_truncated': False, 'artifact_id': 'artifact-1'}
    assert artifacts.cleaned == [str(file_path)]


def test_artifact_send_rejects_unsupported_file_clipboard(tmp_path):
    session = FakeClipboardSession(files=False)
    api = WebClipboardApi(session, FakeArtifactStore(tmp_path / 'unused'))
    with pytest.raises(RuntimeError, match='Target clipboard does not support files'):
        api.set_artifact_file('ios-client', 'artifact-1')
    assert session.sent == []


def test_generic_uploaded_files_use_same_files_kind(tmp_path):
    session = FakeClipboardSession(files=True)
    api = WebClipboardApi(session, FakeArtifactStore(tmp_path / 'unused'))
    staged = tmp_path / 'staged.txt'
    staged.write_text('data', encoding='utf-8')
    api._stage_upload = lambda upload: ({'name': upload.filename, 'url': '/api/temporary/file'}, str(staged))
    result = api.set_files('win-client', [SimpleNamespace(filename='note.txt')], json.dumps({
        'roots': ['note.txt'],
        'entries': [{'type': 'file', 'path': 'note.txt', 'upload_index': 0}],
    }))
    assert result == {'ok': True}
    assert session.sent[0][1]['kind'] == 'files'
    assert session.sent[0][1]['roots'] == ['note.txt']
