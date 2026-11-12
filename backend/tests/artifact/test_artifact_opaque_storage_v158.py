"""Opaque Artifact entity storage: one ID, one file, two-char shard."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.persistence.rch_database import RchDatabase


@pytest.fixture
def catalog(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'artifacts'
    root.mkdir()
    result = ArtifactSqliteCatalog(db, root)
    yield result, root
    db.close_thread_connection()


def test_canonical_object_identity_is_extensionless_and_sharded(catalog):
    store, root = catalog
    identifier = 'f1' * 16
    relative = store.object_relative_path(identifier)
    assert relative.as_posix() == 'objects/f1/' + identifier
    assert not relative.suffix
    full_path = Path(store.physical_path(relative.as_posix()))
    assert full_path == root / relative
    for bad_id in ('', '../oops', 'f' * 31, 'F1' * 16, 'a' * 32 + '.png'):
        with pytest.raises(ValueError, match='Invalid Artifact ID'):
            store.object_relative_path(bad_id)


def test_catalog_keeps_display_extension_but_never_stores_it_in_path(catalog):
    store, root = catalog
    identifier = 'f1' * 16
    relative = store.object_relative_path(identifier)
    target = root / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b'PNG')
    item = store.save({
        'artifact_id': identifier, 'artifact_type': 'saved', 'category': 'screenshots',
        'original_name': '截图.png', 'size': 3, 'machine_id': 'mac-1',
        'saved_at': '2026-11-12 10:00:00', 'saved_path': str(target),
        'extra': {'saved_from': 'client_command'},
    })
    assert item['original_name'] == '截图.png'
    assert item['saved_path'] == relative.as_posix()
    assert item['stored_name'] == identifier
    assert store.get(identifier) == item
    assert store.list(category='screenshots') == [item]


def test_catalog_rejects_noncanonical_paths_even_inside_root(catalog):
    store, root = catalog
    identifier = 'ab' * 16
    for wrong_path in ('objects/report.png', 'objects/ab/' + 'cd' * 16,
                       'preview/machine/test.png', 'objects/ab/' + identifier + '.png'):
        with pytest.raises(ValueError, match='does not match ID'):
            store.save({
                'artifact_id': identifier, 'artifact_type': 'preview',
                'original_name': 'example.png', 'size': 0,
                'saved_at': '2026-11-12 10:00:00', 'saved_path': wrong_path,
            })


def test_registry_allows_text_image_shared_and_preview_same_storage(catalog):
    pytest.importorskip('werkzeug')
    from server.application.artifact.artifact_registry_service import ArtifactRegistryService

    store, root = catalog
    service = SimpleNamespace(database=store.database, artifacts_root_dir=str(root))
    registry = ArtifactRegistryService(service)

    for kind, category, name in (
        ('saved', 'screenshots', 'capture.png'),
        ('shared', '', '评估.txt'),
        ('preview', '', 'preview.jpeg'),
    ):
        item = registry.save_text_artifact(
            artifact_type=kind, category=category, hostname='mac', machine_id='machine',
            original_name=name, content='hello',
        )
        path = Path(registry.get_artifact_file_path(item['artifact_id']))
        assert path.name == item['artifact_id']
        assert path.parent.name == item['artifact_id'][:2]
        assert path.read_text() == 'hello'
        assert item['original_name'] == name
        assert item['saved_path'] == store.object_relative_path(item['artifact_id']).as_posix()
        assert path.suffix == ''
        registry.delete_artifact(item['artifact_id'])
        assert not path.exists()


def test_file_upload_and_copy_from_preview_keep_new_ids(catalog):
    pytest.importorskip('werkzeug')
    from server.application.artifact.artifact_registry_service import ArtifactRegistryService

    store, root = catalog
    service = SimpleNamespace(database=store.database, artifacts_root_dir=str(root))
    registry = ArtifactRegistryService(service)

    class Upload:
        filename = 'sample.png'

        def save(self, path, buffer_size=None):
            Path(path).write_bytes(b'\x89PNG\r\n\x1a\nDATA')

    original = registry.save_http_uploaded_file(Upload(), artifact_type='preview', machine_id='machine')
    from server.application.artifact.artifact_preview_service import ArtifactPreviewService
    service.registry_service = registry
    service.MAX_PREVIEW_TEXT_BYTES = 524288
    service.get_artifact_file_path = registry.get_artifact_file_path
    previewer = ArtifactPreviewService(service)
    assert previewer.build_preview_payload(original['artifact_id'])['type'] == 'image'
    copied = registry.save_preview_to_saved(original['artifact_id'])
    assert copied['artifact_type'] == 'saved'
    assert copied['original_name'] == 'sample.png'
    assert original['artifact_id'] != copied['artifact_id']
    assert original['saved_path'] != copied['saved_path']
    assert Path(registry.get_artifact_file_path(copied['artifact_id'])).read_bytes() == b'\x89PNG\r\n\x1a\nDATA'


def test_command_output_uses_one_allocation_id_for_saved_file(catalog):
    pytest.importorskip('werkzeug')
    from server.application.artifact.artifact_registry_service import ArtifactRegistryService
    from server.application.artifact.command_output_artifact_service import CommandOutputArtifactService

    store, root = catalog
    service = SimpleNamespace(database=store.database, artifacts_root_dir=str(root))
    registry = ArtifactRegistryService(service)
    service.allocate_artifact_path = registry.allocate_artifact_path
    service.register_existing_artifact = registry.register_existing_artifact
    service.get_artifact_file_path = registry.get_artifact_file_path
    output_service = CommandOutputArtifactService(service)
    item = output_service.save_text_output(
        content='ok', output_kind='command', hostname='mac', machine_id='mac-id',
        source_command='whoami', extra={'saved_from': 'terminal_output'},
    )
    assert item['category'] == 'command_output'
    assert item['original_name'].endswith('.txt')
    assert Path(service.get_artifact_file_path(item['artifact_id'])).name == item['artifact_id']


def test_cleanup_only_deletes_preview_snapshot_not_saved_or_later_preview(catalog):
    pytest.importorskip('werkzeug')
    from server.application.artifact.artifact_registry_service import ArtifactRegistryService
    from server.application.maintenance.server_cleanup_service import ServerCleanupService

    store, root = catalog
    service = SimpleNamespace(database=store.database, artifacts_root_dir=str(root))
    service.registry_service = ArtifactRegistryService(service)
    service.list_artifacts = service.registry_service.list_artifacts
    service.get_artifact_by_id = service.registry_service.get_artifact_by_id
    service.delete_artifact = service.registry_service.delete_artifact
    first = service.registry_service.save_text_artifact(
        artifact_type='preview', category='', hostname='mac', machine_id='machine',
        original_name='first.txt', content='first',
    )
    saved = service.registry_service.save_text_artifact(
        artifact_type='saved', category='inbox', hostname='mac', machine_id='machine',
        original_name='saved.txt', content='saved',
    )
    cleaner = ServerCleanupService.__new__(ServerCleanupService)
    cleaner.artifact_service = service
    snapshot = cleaner._snapshot_preview_cache()
    second = service.registry_service.save_text_artifact(
        artifact_type='preview', category='', hostname='mac', machine_id='machine',
        original_name='later.txt', content='later',
    )
    assert snapshot == [first['artifact_id']]
    removed = cleaner._cleanup_preview_cache(snapshot)
    assert removed['removed_files'] == 1
    assert removed['removed_records'] == 1
    assert store.get(first['artifact_id']) is None
    assert store.get(second['artifact_id']) is not None
    assert store.get(saved['artifact_id']) is not None
    assert Path(service.registry_service.get_artifact_file_path(saved['artifact_id'])).exists()


def test_extensionless_archive_and_text_preview_are_classified_by_bytes(catalog):
    pytest.importorskip('werkzeug')
    import io
    import zipfile
    from server.application.artifact.artifact_registry_service import ArtifactRegistryService
    from server.application.artifact.artifact_preview_service import ArtifactPreviewService

    store, root = catalog
    service = SimpleNamespace(database=store.database, artifacts_root_dir=str(root))
    registry = ArtifactRegistryService(service)
    service.registry_service = registry
    service.MAX_PREVIEW_TEXT_BYTES = 524288
    service.get_artifact_file_path = registry.get_artifact_file_path
    preview = ArtifactPreviewService(service)
    text = registry.save_text_artifact(
        artifact_type='shared', category='', hostname='', machine_id='',
        original_name='中文.txt', content='document',
    )
    assert preview.build_preview_payload(text['artifact_id'])['type'] == 'text'
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('a.txt', 'a')
    class Upload:
        filename = 'bundle.zip'
        def save(self, path, buffer_size=None):
            Path(path).write_bytes(data.getvalue())
    zipped = registry.save_http_uploaded_file(Upload(), artifact_type='saved', category='downloads')
    assert preview.build_preview_payload(zipped['artifact_id'])['type'] == 'archive'
    assert Path(registry.get_artifact_file_path(zipped['artifact_id'])).suffix == ''
