"""Script SDK and upload request producers send category for Saved, folder for Shared."""
from unittest.mock import Mock

import pytest

from core.artifact_contract import classify_artifact
from client.runtime.sdk import artifact


def test_canonical_classification_is_independent_of_command_output_naming():
    assert artifact.upload is artifact.save
    assert classify_artifact('files', 'script_files') == ('saved', 'script_files', 'saved:script_files')
    assert classify_artifact('files', 'SCRIPT_FILES') == ('saved', 'script_files', 'saved:script_files')
    assert classify_artifact('files', 'script_file') == ('saved', 'inbox', 'saved:inbox')
    assert classify_artifact('files', '') == ('saved', 'inbox', 'saved:inbox')
    assert classify_artifact('command_output', 'command_output')[2] == 'saved:command_output'
    for old in ('screenshot', 'script_output', 'job_output'):
        assert classify_artifact('files', old)[1] == 'inbox'


def test_script_sdk_uses_saved_category_and_shared_folder(monkeypatch, tmp_path):
    file_path = tmp_path / 'demo.png'
    file_path.write_bytes(b'bytes')
    monkeypatch.setattr(artifact, 'get_command_owner', lambda: None)
    monkeypatch.setattr(artifact, 'get_client_id', lambda: 'client-1')
    monkeypatch.setattr(artifact, 'get_command_id', lambda: 24)
    recorded = []

    class Response:
        def raise_for_status(self):
            pass

    class Client:
        def upload_file_source(self, path, *, filename, form_data, timeout):
            recorded.append(form_data)
            return Response()

        def try_parse_json(self, response):
            return {'code': 0, 'data': {'artifact_id': 'abc'}}

    monkeypatch.setattr(artifact, 'ClientApiClient', Client)
    artifact.upload(str(file_path), category='screenshots')
    assert recorded[-1]['category'] == 'screenshots'
    assert 'folder' not in recorded[-1]
    artifact.save(str(file_path))
    assert 'category' not in recorded[-1]  # no SDK input -> Server Inbox
    artifact.save(str(file_path), type='shared_files', folder='Team/Tools')
    assert recorded[-1]['folder'] == 'Team/Tools'
    assert 'category' not in recorded[-1]
    with pytest.raises(ValueError, match='Saved Files'):
        artifact.save(str(file_path), folder='Screenshots')
    with pytest.raises(ValueError, match='Only Saved Files'):
        artifact.save(str(file_path), type='shared_files', category='inbox')


def test_shared_folder_resolution_by_name_and_nested_path(tmp_path):
    from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
    from server.persistence.rch_database import RchDatabase
    catalog = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    assert catalog.resolve_folder('saved', 'Screenshots') == 'saved:screenshots'
    assert catalog.resolve_folder('saved', 'script files') == 'saved:script_files'
    assert catalog.resolve_folder('saved', 'Job Files') == 'saved:job_files'
    with pytest.raises(ValueError, match='Unknown'):
        catalog.resolve_folder('saved', 'New Folder')
    team = catalog.create_folder('shared', 'Team')
    tools = catalog.create_folder('shared', 'Tools', team['folder_id'])
    assert catalog.resolve_folder('shared', 'Team/Tools') == tools['folder_id']
    with pytest.raises(ValueError, match='Unknown'):
        catalog.resolve_folder('shared', 'Tools')
    with pytest.raises(ValueError, match='Invalid'):
        catalog.resolve_folder('shared', 'Team/../Tools')


def test_script_http_upload_form_uses_category_and_preserves_identity():
    from client.http.script_upload_api import _build_script_upload_form_data
    data = _build_script_upload_form_data(category='screenshots', context={'client_id': 'id-1', 'command_id': 17})
    assert data['category'] == 'screenshots'
    assert 'folder' not in data
    assert data['source_command_id'] == 17
    assert 'category' not in _build_script_upload_form_data()
    assert 'category' not in _build_script_upload_form_data(artifact_type='shared_files', folder='Team')
    with pytest.raises(ValueError, match='Saved Files'):
        _build_script_upload_form_data(folder='Script Files')


def test_sdk_owner_upload_forwards_explicit_category(monkeypatch, tmp_path):
    from types import SimpleNamespace
    source = tmp_path / 'generated.txt'
    source.write_text('abc')
    calls = []

    class Response:
        def raise_for_status(self):
            pass

    class Api:
        def try_parse_json(self, response):
            return {'code': 0, 'data': {'artifact_id': 'id-1'}}

    class Transfer:
        def upload_file_to_server_via_http(self, file_path, **kwargs):
            calls.append(kwargs)
            return Response()

    owner = SimpleNamespace(http_file_transfer_service=Transfer(),
                            path_resolver=SimpleNamespace(require_existing_file_from_arg=lambda p: p))
    monkeypatch.setattr(artifact, 'get_command_owner', lambda: owner)
    monkeypatch.setattr(artifact, 'ClientApiClient', Api)
    artifact.save(str(source), category='screenshots')
    assert calls == [{'artifact_type': 'files', 'category': 'screenshots', 'folder': '',
                      'extra': {'origin': 'script'}}]


def test_web_api_passes_saved_category_without_folder_to_storage(tmp_path):
    from server.application.web.artifact_api import WebArtifactApi
    service = Mock()
    service.save_http_uploaded_file.return_value = {'artifact_id': 'id-1', 'scope': 'saved'}
    api = WebArtifactApi(server=None, event_bus=None, artifact_service=service)
    result = api.save_http_uploaded_file(Mock(), artifact_type='files', category='SCREenshots')
    assert result['artifact_id'] == 'id-1'
    assert service.save_http_uploaded_file.call_args.kwargs['category'] == 'SCREenshots'
    assert service.save_http_uploaded_file.call_args.kwargs['folder_id'] == ''
    service.move_artifact.assert_not_called()
