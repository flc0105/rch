"""Unicode-only display renames and Job file association time regression."""

from types import SimpleNamespace

import pytest

from server.application.artifact.artifact_registry_service import ArtifactRegistryService
from server.application.jobs.background_job_store import BackgroundJobStore
from server.persistence.rch_database import RchDatabase


@pytest.fixture
def artifact_registry(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'artifacts'
    file_path = root / 'objects' / 'original_abcd1234.txt'
    file_path.parent.mkdir(parents=True)
    file_path.write_text('original contents', encoding='utf-8')
    registry = ArtifactRegistryService(SimpleNamespace(
        database=database, artifacts_root_dir=str(root),
    ))
    registry.catalog.save({
        'artifact_id': 'artifact-1', 'artifact_type': 'saved', 'category': 'downloads',
        'original_name': 'before.txt', 'size': file_path.stat().st_size,
        'machine_id': 'macbook', 'client_id': 'client-1',
        'saved_at': '2026-11-12 09:31:48', 'saved_path': 'objects/original_abcd1234.txt',
        'extra': {},
    })
    yield registry, database, file_path
    database.close_thread_connection()


@pytest.mark.parametrize('new_name', [
    '评估两个需求', '报告 2026.txt', 'résumé final.txt', '📁归档报告.json',
])
def test_rename_preserves_unicode_and_file_identity(artifact_registry, new_name):
    registry, db, path = artifact_registry
    renamed = registry.rename_artifact('artifact-1', new_name)
    assert renamed['original_name'] == new_name
    assert renamed['saved_at'] == '2026-11-12 09:31:48'
    assert renamed['stored_name'] == 'original_abcd1234.txt'
    assert renamed['saved_path'] == 'objects/original_abcd1234.txt'
    assert renamed['category'] == 'downloads'
    assert path.read_text(encoding='utf-8') == 'original contents'
    assert registry.catalog.get('artifact-1')['original_name'] == new_name
    assert db.connection().execute('SELECT original_name FROM artifact_entries').fetchone()[0] == new_name


@pytest.mark.parametrize('bad_name', ['', '   ', '.', '..', 'bad/name', 'bad\\name',
                                      'bad\nname', 'bad\x00name', '\ud800', 'x' * 256])
def test_rename_rejects_invalid_metadata_names(artifact_registry, bad_name):
    registry, _, _ = artifact_registry
    with pytest.raises(ValueError, match='new name is invalid'):
        registry.rename_artifact('artifact-1', bad_name)
    assert registry.catalog.get('artifact-1')['original_name'] == 'before.txt'


def test_job_file_view_uses_association_time_not_old_created_at(artifact_registry):
    registry, db, _ = artifact_registry
    store = BackgroundJobStore(db)
    store.artifact_service = registry
    store.apply_status_report({
        'job_id': 'job-1', 'client_id': 'client-1', 'machine_id': 'macbook',
        'job_key': 'clipboard_monitor', 'state': 'running',
        'time': '2026-11-12T09:31:35',
    })
    store.link_artifact('job-1', registry.get_artifact_by_id('artifact-1'))
    with db.transaction() as conn:
        conn.execute('''UPDATE background_job_files SET linked_at=?
                        WHERE job_id=? AND artifact_id=?''',
                     ('2026-11-12T09:31:48', 'job-1', 'artifact-1'))
    job = store.get_job_for_scope('job-1', machine_id='macbook')
    assert len(job['files']) == 1
    attached = job['files'][0]
    assert attached['original_name'] == 'before.txt'
    assert attached['linked_at'] == '2026-11-12T09:31:48'
    assert 'created_at' not in attached
    assert attached['is_available'] is True
