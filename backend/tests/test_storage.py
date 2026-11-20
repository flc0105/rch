"""Persistent data, artifact identity and document revisions."""

from types import SimpleNamespace

import pytest

from server.application.artifact.artifact_registry_service import ArtifactRegistryService
from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.application.documents.document_library_service import DocumentLibraryService
from server.persistence.rch_database import RchDatabase


@pytest.fixture
def catalog(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'artifacts'
    root.mkdir()
    result = ArtifactSqliteCatalog(db, root)
    yield result, root
    db.close_thread_connection()


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


@pytest.fixture
def artifact_registry(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'artifacts'
    file_path = root / 'objects' / 'a1' / ('a1' * 16)
    file_path.parent.mkdir(parents=True)
    file_path.write_text('original contents', encoding='utf-8')
    registry = ArtifactRegistryService(SimpleNamespace(
        database=database, artifacts_root_dir=str(root),
    ))
    registry.catalog.save({
        'artifact_id': 'a1' * 16, 'artifact_type': 'saved', 'category': 'downloads',
        'original_name': 'before.txt', 'size': file_path.stat().st_size,
        'machine_id': 'macbook', 'client_id': 'client-1',
        'saved_at': '2026-11-12 09:31:48', 'saved_path': 'objects/a1/' + ('a1' * 16),
        'extra': {},
    })
    yield registry, database, file_path
    database.close_thread_connection()


def test_rename_preserves_unicode_and_file_identity(artifact_registry):
    new_name = '报告 résumé 📁.json'
    registry, db, path = artifact_registry
    renamed = registry.rename_artifact('a1' * 16, new_name)
    assert renamed['original_name'] == new_name
    assert renamed['saved_at'] == '2026-11-12 09:31:48'
    assert renamed['stored_name'] == 'a1' * 16
    assert renamed['saved_path'] == 'objects/a1/' + ('a1' * 16)
    assert renamed['category'] == 'downloads'
    assert path.read_text(encoding='utf-8') == 'original contents'
    assert registry.catalog.get('a1' * 16)['original_name'] == new_name
    assert db.connection().execute('SELECT original_name FROM artifact_entries').fetchone()[0] == new_name


def test_existing_final_database_preserves_data_and_unrelated_tables(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.connection().execute("INSERT INTO settings(namespace,value_json) VALUES ('test', '{\"ok\":true}')")
    db.connection().execute('CREATE TABLE external_app_table (value TEXT)')
    db.connection().execute("INSERT INTO external_app_table VALUES ('retained')")
    db.close_thread_connection()
    reopened = RchDatabase(str(path))
    assert reopened.connection().execute("SELECT value_json FROM settings WHERE namespace='test'").fetchone()[0] == '{"ok":true}'
    assert reopened.connection().execute('SELECT value FROM external_app_table').fetchone()[0] == 'retained'
    reopened.close_thread_connection()


@pytest.fixture
def library(tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    return DocumentLibraryService({'notes': {'label': 'Notes', 'path': str(root)}}, 512 * 1024)


def test_conflict_preserves_external_changes(library, tmp_path):
    doc = library.create_document('notes', 'a.md')
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'external editor')
    with pytest.raises(ValueError, match='changed on disk'):
        library.save_document('notes', 'a.md', 'overwritten', 'utf-8', doc['sha256'])
    assert path.read_bytes() == b'external editor'


def test_document_write_cannot_escape_its_root(library, tmp_path):
    external = tmp_path / 'outside.md'
    external.write_bytes(b'outside data')
    with pytest.raises(ValueError):
        library.create_document('notes', '../outside.md')
    assert external.read_bytes() == b'outside data'
