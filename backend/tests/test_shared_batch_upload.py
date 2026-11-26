"""Shared upload batching preserves folder identity and emits one notification."""
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.application.web.artifact_api import WebArtifactApi
from server.application.artifact.shared_upload_service import SharedUploadService
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
        def list_folders(self, kind): return catalog.list_folders(kind)
        def shared_file_names(self): return catalog.shared_file_names()
        def inspect_shared_upload(self, *args): return SharedUploadService(self).inspect(*args)
        def upload_shared_batch(self, **kwargs): return SharedUploadService(self).upload(**kwargs)
        def save_shared_upload_file(self, upload, folder_id, policy):
            if policy == 'stop' and catalog.shared_file_exists(folder_id, upload.filename): raise ValueError('Destination changed')
            return self.save_http_uploaded_file(upload, artifact_type='shared', folder_id=folder_id)

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
                                     directories=['docs', 'docs/nested', 'docs/empty'], conflict_policies=['stop']*100)
    assert result == {'files_uploaded': 100, 'folders_created': 3, 'files_skipped': 0}
    dirs = catalog.list_folders(artifact_type='shared')
    by_name = {d['name']: d for d in dirs}
    assert by_name['nested']['parent_id'] == by_name['docs']['folder_id']
    assert by_name['empty']['parent_id'] == by_name['docs']['folder_id']
    rows = catalog.list(artifact_type='shared')
    assert len(rows) == 100
    assert {row['folder_id'] for row in rows} == {by_name['nested']['folder_id']}
    assert events.items == [('artifact_batch_uploaded', {
        'artifact_type': 'shared', 'file_count': 100, 'folder_count': 3, 'skipped_files': 0,
    })]
    notification = NotificationEventProjector(history_store=None, server=None)._build_artifact_batch_uploaded(events.items[0][1])
    assert notification['notification_key'] == 'artifact_created'
    assert notification['message'].startswith('100 file(s)')


def test_shared_batch_reuses_existing_folder_under_selected_parent(service):
    api, catalog, events = service
    parent = catalog.create_folder('shared', 'Destination', '')['folder_id']
    nested = catalog.create_folder('shared', 'docs', parent)['folder_id']
    result = api.upload_shared_batch(files=[UploadFile('a.txt')], paths=['docs/a.txt'],
                                     directories=['docs'], parent_folder_id=parent, conflict_policies=['stop'])
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
        api.upload_shared_batch(files=files, paths=paths, directories=dirs, conflict_policies=['stop']*len(files))
    assert catalog.list(artifact_type='shared') == []
    assert events.items == []


def test_partial_shared_batch_reports_actual_committed_files(service, monkeypatch):
    api, catalog, events = service
    original = api.artifact_service.save_http_uploaded_file
    def save(upload, **kwargs):
        if upload.filename == 'b.txt':
            raise OSError('Disk full')
        return original(upload, **kwargs)
    monkeypatch.setattr(api.artifact_service, 'save_http_uploaded_file', save)
    with pytest.raises(ValueError, match='1/2'):
        api.upload_shared_batch(files=[UploadFile('a.txt'), UploadFile('b.txt')],
                                paths=['docs/a.txt', 'docs/b.txt'], directories=['docs'], conflict_policies=['stop','stop'])
    assert len(catalog.list(artifact_type='shared')) == 1
    kind, payload = events.items[0]
    assert kind == 'artifact_batch_uploaded' and payload['file_count'] == 1
    assert payload['total_files'] == 2 and payload['error'] == 'Disk full'
    notification = NotificationEventProjector(history_store=None, server=None)._build_artifact_batch_uploaded(payload)
    assert notification['title'] == 'Shared Upload Incomplete'


def test_shared_conflict_decisions_and_validation(service):
    api, catalog, _ = service
    def submit(policy, path='docs/a.txt'):
        return api.upload_shared_batch(files=[UploadFile('a.txt')], paths=[path], directories=[], conflict_policies=[policy])
    submit('stop')
    assert api.inspect_shared_upload(['docs/a.txt'], [], '')['conflicts'][0]['allowed_actions'] == ['stop','skip','keep_both']
    with pytest.raises(ValueError, match='conflict'): submit('stop')
    assert submit('skip')['files_skipped'] == 1
    assert submit('keep_both')['files_uploaded'] == 1
    assert len(catalog.list(artifact_type='shared')) == 2
    with pytest.raises(ValueError, match='Invalid Shared upload path'): submit('stop','new/ bad/a.txt')
    assert {row['name'] for row in catalog.list_folders('shared')} == {'docs'}


def test_shared_root_conflicts_use_null_folder_identity(service):
    api, catalog, _ = service
    args = dict(files=[UploadFile('a.txt')], paths=['a.txt'], directories=[], conflict_policies=['stop'])
    api.upload_shared_batch(**args)
    assert catalog.shared_file_exists('', 'a.txt')
    assert api.inspect_shared_upload(['a.txt'], [], '')['conflicts']
    with pytest.raises(ValueError, match='conflict'):
        api.upload_shared_batch(**args)
