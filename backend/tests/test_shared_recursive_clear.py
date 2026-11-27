"""Shared Clear and Delete Folder remove physical objects and only their logical subtree."""
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.persistence.rch_database import RchDatabase


@pytest.fixture
def registry(tmp_path):
    pytest.importorskip('werkzeug')
    from server.application.artifact.artifact_registry_service import ArtifactRegistryService

    database = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'artifacts'
    root.mkdir()
    service = ArtifactRegistryService(SimpleNamespace(database=database, artifacts_root_dir=str(root)))
    yield service
    database.close_thread_connection()


def folder(registry, name, parent=''):
    return registry.create_folder('shared', name, parent)['folder_id']


def file(registry, name, parent='', kind='shared'):
    artifact_id = uuid.uuid4().hex
    relative = registry.catalog.object_relative_path(artifact_id)
    path = registry.catalog.storage_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'test')
    payload = dict(artifact_id=artifact_id, artifact_type=kind, original_name=name,
                   folder_id=parent, size=4, saved_at='2026-11-26 12:00:00',
                   saved_path=relative.as_posix())
    if kind == 'saved':
        payload['category'] = 'inbox'
    registry.catalog.save(payload)
    return artifact_id, path


def test_clear_selected_folder_preserves_self_siblings_saved_and_preview(registry):
    a = folder(registry, 'a'); child = folder(registry, 'child', a)
    deep = folder(registry, 'deep', child); empty = folder(registry, 'empty', a)
    sibling = folder(registry, 'sibling')
    removed = [file(registry, 'direct', a), file(registry, 'nested', deep)]
    retained = [file(registry, 'outside', sibling), file(registry, 'root'),
                file(registry, 'saved', kind='saved'), file(registry, 'preview', kind='preview')]
    result = registry.clear_artifacts('shared', folder_id=a)
    assert result['deleted_count'] == 2
    assert result['deleted_folder_count'] == 3
    assert {f['folder_id'] for f in registry.list_folders('shared')} == {a, sibling}
    for artifact_id, path in removed:
        assert not path.exists() and registry.catalog.get(artifact_id) is None
    for artifact_id, path in retained:
        assert path.exists() and registry.catalog.get(artifact_id) is not None
    assert registry.clear_artifacts('shared', folder_id=a)['deleted_count'] == 0


def test_delete_nonempty_folder_recursively_and_root_clear(registry):
    a = folder(registry, 'a'); b = folder(registry, 'b', a)
    nested = file(registry, 'nested', b); direct = file(registry, 'direct', a)
    root_file = file(registry, 'root'); sibling = folder(registry, 'other')
    result = registry.delete_folder(a)
    assert result == {'folder_id': a, 'deleted_count': 2, 'deleted_folder_count': 2}
    assert not nested[1].exists() and not direct[1].exists()
    assert root_file[1].exists()
    assert registry.list_folders('shared')[0]['folder_id'] == sibling
    assert registry.clear_artifacts('shared')['deleted_folder_count'] == 1
    assert registry.list_folders('shared') == []
    assert registry.catalog.list(artifact_type='shared') == []
    assert not root_file[1].exists()


def test_invalid_folder_and_device_filter_do_not_expand_scope(registry):
    folder_id = folder(registry, 'keep')
    artifact_id, path = file(registry, 'keep', folder_id)
    saved_folder = registry.list_folders('saved')[0]['folder_id']
    for target in ('missing', saved_folder):
        with pytest.raises(FileNotFoundError):
            registry.clear_artifacts('shared', folder_id=target)
        with pytest.raises(FileNotFoundError):
            registry.delete_folder(target)
    with pytest.raises(ValueError):
        registry.delete_folder('')
    with pytest.raises(ValueError):
        registry.clear_artifacts('shared', machine_id='machine')
    assert path.exists() and registry.catalog.get(artifact_id) is not None


def test_unlink_failure_preserves_catalog_and_folder(registry, monkeypatch):
    folder_id = folder(registry, 'keep')
    artifact_id, path = file(registry, 'keep', folder_id)
    unlink = Path.unlink
    def fail_for_target(self, *args, **kwargs):
        if self == path:
            raise PermissionError('test failure')
        return unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail_for_target)
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        registry.delete_folder(folder_id)
    assert path.exists() and registry.catalog.get(artifact_id) is not None
    assert registry.catalog.get_folder(folder_id)


def test_missing_file_can_be_removed_but_symlink_does_not_delete_target(registry):
    folder_id = folder(registry, 'a')
    artifact_id, path = file(registry, 'missing', folder_id)
    path.unlink()
    assert registry.clear_artifacts('shared', folder_id=folder_id)['deleted_count'] == 1
    assert registry.catalog.get(artifact_id) is None
    linked_id, link_path = file(registry, 'linked', folder_id)
    other_id, other_path = file(registry, 'keep')
    link_path.unlink(); link_path.symlink_to(other_path)
    with pytest.raises(RuntimeError, match='Unsafe Artifact storage path'):
        registry.delete_folder(folder_id)
    assert other_path.exists() and link_path.is_symlink()
    assert registry.catalog.get(linked_id) and registry.catalog.get(other_id)
