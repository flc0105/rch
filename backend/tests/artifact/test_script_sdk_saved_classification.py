from client.runtime.sdk import artifact
from server.application.artifact.artifact_sqlite_catalog import classify_artifact


def test_folder_and_output_categories_have_distinct_meanings():
    assert artifact.upload is artifact.save
    assert classify_artifact('files', 'script_file') == ('saved', 'script_file', 'saved:script_file')
    assert classify_artifact('files', '') == ('saved', 'inbox', 'saved:inbox')
    assert classify_artifact('files', 'screenshots') == ('saved', 'screenshots', 'saved:screenshots')
    assert classify_artifact('command_output', 'command_output')[2] == 'saved:command_output'
    import pytest
    for source in ('screenshot', 'script_output', 'job_output'):
        with pytest.raises(ValueError):
            classify_artifact('command_output', source)


def test_script_sdk_uses_folder_not_category(monkeypatch, tmp_path):
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
    artifact.upload(str(file_path), folder='Screenshots')
    assert recorded[-1]['folder'] == 'Screenshots'
    assert 'source_kind' not in recorded[-1]
    assert 'category' not in recorded[-1]
    artifact.save(str(file_path))
    assert recorded[-1]['folder'] == 'Script Files'
    artifact.save(str(file_path), type='shared_files', folder='Team/Tools')
    assert recorded[-1]['folder'] == 'Team/Tools'
    assert 'source_kind' not in recorded[-1]
    import pytest
    with pytest.raises(TypeError):
        artifact.save(str(file_path), category='screenshot')


def test_folder_resolution_by_display_name_and_shared_path(tmp_path):
    import pytest
    from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
    catalog = ArtifactSqliteCatalog(str(tmp_path / 'catalog.sqlite3'))
    assert catalog.resolve_folder('saved', 'Screenshots') == 'saved:screenshots'
    assert catalog.resolve_folder('saved', 'script files') == 'saved:script_file'
    assert catalog.resolve_folder('saved', 'Job Files') == 'saved:job_file'
    with pytest.raises(ValueError, match='Unknown'):
        catalog.resolve_folder('saved', 'New Folder')
    team = catalog.create_folder('shared', 'Team')
    tools = catalog.create_folder('shared', 'Tools', team['folder_id'])
    assert catalog.resolve_folder('shared', 'Team/Tools') == tools['folder_id']
    with pytest.raises(ValueError, match='Unknown'):
        catalog.resolve_folder('saved', 'Team/Tools')
    with pytest.raises(ValueError, match='Unknown'):
        catalog.resolve_folder('shared', 'Tools')
    with pytest.raises(ValueError, match='Invalid'):
        catalog.resolve_folder('shared', 'Team/../Tools')


def test_http_upload_folder_is_validated_before_file_write(tmp_path):
    from unittest.mock import Mock
    import pytest
    from server.application.web.artifact_api import WebArtifactApi
    from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
    catalog = ArtifactSqliteCatalog(str(tmp_path / 'catalog.sqlite3'))
    service = Mock()
    service.registry_service.catalog = catalog
    api = WebArtifactApi(server=None, event_bus=None, artifact_service=service)
    with pytest.raises(ValueError, match='Unknown'):
        api.save_http_uploaded_file(Mock(), artifact_type='files', folder='not-a-folder')
    service.save_http_uploaded_file.assert_not_called()
    with pytest.raises(ValueError, match='Specify folder or folder_id'):
        api.save_http_uploaded_file(Mock(), artifact_type='files', folder='Screenshots', folder_id='saved:screenshots')
    service.save_http_uploaded_file.assert_not_called()


def test_script_file_like_upload_form_uses_folder_not_category():
    from client.http.script_upload_api import _build_script_upload_form_data
    data = _build_script_upload_form_data(folder='Screenshots', context={'client_id': 'id-1', 'command_id': 17})
    assert 'source_kind' not in data
    assert data['folder'] == 'Screenshots'
    assert 'category' not in data
    assert data['source_command_id'] == 17


def test_sdk_owner_upload_forwards_explicit_folder(monkeypatch, tmp_path):
    from types import SimpleNamespace
    path = tmp_path / 'generated.txt'
    path.write_text('abc')
    calls = []
    class Response:
        def raise_for_status(self):
            return None
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
    artifact.save(str(path), folder='Screenshots')
    assert calls == [{'artifact_type': 'files', 'folder': 'Screenshots',
                      'extra': {'origin': 'script'}}]


def test_web_upload_resolves_folder_before_persisting(tmp_path):
    from unittest.mock import Mock
    from server.application.web.artifact_api import WebArtifactApi
    from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
    catalog = ArtifactSqliteCatalog(str(tmp_path / 'catalog.sqlite3'))
    service = Mock()
    service.registry_service.catalog = catalog
    service.save_http_uploaded_file.return_value = {'artifact_id': 'id-1', 'scope': 'saved'}
    service.move_artifact.return_value = {'artifact_id': 'id-1', 'folder_id': 'saved:screenshots'}
    api = WebArtifactApi(server=None, event_bus=None, artifact_service=service)
    result = api.save_http_uploaded_file(Mock(), artifact_type='files', folder='Screenshots')
    assert result['artifact_id'] == 'id-1'
    assert service.save_http_uploaded_file.call_args.kwargs['source_kind'] == ''
    assert service.save_http_uploaded_file.call_args.kwargs['folder_id'] == 'saved:screenshots'
    service.move_artifact.assert_not_called()
