"""Shared upload batching preserves folder identity and emits one notification."""
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.application.web.artifact_api import WebArtifactApi
from server.application.preferences.notification_event_projector import NotificationEventProjector
from server.persistence.rch_database import RchDatabase


class UploadFile:
    def __init__(self, name, content=b'hello'):
        self.filename = name
        self.content = content


class Events:
    def __init__(self):
        self.items = []

    def publish(self, kind, payload):
        self.items.append((kind, payload))


@pytest.fixture
def service(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'storage'
    root.mkdir()
    catalog = ArtifactSqliteCatalog(db, root)

    class Artifacts:
        registry_service = SimpleNamespace(catalog=catalog)

        def create_folder(self, kind, name, parent_id):
            return catalog.create_folder(kind, name, parent_id)

        def save_http_uploaded_file(self, upload, **kwargs):
            identifier = uuid.uuid4().hex
            relative = catalog.object_relative_path(identifier)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(upload.content)
            return catalog.save({
                'artifact_id': identifier,
                'artifact_type': kwargs['artifact_type'],
                'folder_id': kwargs['folder_id'],
                'original_name': upload.filename,
                'size': len(upload.content),
                'saved_at': '2026-11-26 12:00:00',
                'saved_path': relative.as_posix(),
            })

    events = Events()
    api = WebArtifactApi(server=None, event_bus=events, artifact_service=Artifacts())
    yield api, catalog, events
    db.close_thread_connection()


def test_shared_batch_keeps_nested_folders_empty_dirs_and_100_files(service):
    api, catalog, events = service
    files = [UploadFile(f'file-{i}.txt', str(i).encode()) for i in range(100)]
    paths = [f'docs/nested/file-{i}.txt' for i in range(100)]
    result = api.upload_shared_batch(files=files, paths=paths,
                                     directories=['docs', 'docs/nested', 'docs/empty'])
    assert result == {'files_uploaded': 100, 'folders_created': 3}
    dirs = catalog.list_folders(artifact_type='shared')
    by_name = {d['name']: d for d in dirs}
    assert by_name['nested']['parent_id'] == by_name['docs']['folder_id']
    assert by_name['empty']['parent_id'] == by_name['docs']['folder_id']
    rows = catalog.list(artifact_type='shared')
    assert len(rows) == 100
    assert {row['folder_id'] for row in rows} == {by_name['nested']['folder_id']}
    assert events.items == [('artifact_batch_uploaded', {
        'artifact_type': 'shared', 'file_count': 100, 'folder_count': 3,
    })]
    notification = NotificationEventProjector(history_store=None, server=None)._build_artifact_batch_uploaded(events.items[0][1])
    assert notification['notification_key'] == 'artifact_created'
    assert notification['message'].startswith('100 file(s)')


def test_shared_batch_reuses_existing_folder_under_selected_parent(service):
    api, catalog, events = service
    parent = catalog.create_folder('shared', 'Destination', '')['folder_id']
    nested = catalog.create_folder('shared', 'docs', parent)['folder_id']
    result = api.upload_shared_batch(files=[UploadFile('a.txt')], paths=['docs/a.txt'],
                                     directories=['docs'], parent_folder_id=parent)
    assert result['folders_created'] == 0
    assert catalog.list(artifact_type='shared')[0]['folder_id'] == nested
    assert len(events.items) == 1


@pytest.mark.parametrize('paths,dirs', [
    (['../outside'], []), (['docs/a.txt', 'docs/a.txt'], ['docs']),
    (['docs/a.txt'], ['docs/../escape']), (['docs/a.txt'], ['docs/a.txt']),
])
def test_shared_batch_rejects_invalid_selection_without_writes(service, paths, dirs):
    api, catalog, events = service
    files = [UploadFile('a.txt') for _ in paths]
    with pytest.raises(ValueError):
        api.upload_shared_batch(files=files, paths=paths, directories=dirs)
    assert catalog.list(artifact_type='shared') == []
    assert events.items == []
