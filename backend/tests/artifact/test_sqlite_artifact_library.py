"""SQLite Saved category/Shared folder rules, including the exact nine-category mapping."""
import json
import sqlite3

import pytest

from core.artifact_contract import (
    ArtifactCategory, SAVED_CATEGORY_FOLDERS, SAVED_FOLDER_IDS,
    classify_artifact, normalize_saved_category,
)
from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.persistence.rch_database import RchDatabase


def make_record(path, artifact_id, scope='saved', category='screenshots', folder_id='saved:screenshots'):
    path.write_text('untouched content', encoding='utf-8')
    record = {
        'artifact_id': artifact_id, 'scope': scope,
        'machine_id': 'machine-one' if scope == 'saved' else '',
        'saved_path': str(path), 'original_name': path.name,
        'stored_name': path.name, 'saved_at': '2026-11-10 09:00:00',
    }
    if scope == 'saved':
        record['category'] = category
    if folder_id:
        record['folder_id'] = folder_id
    return record


def test_nine_canonical_categories_have_unique_folder_ids_and_names(tmp_path):
    catalog = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    folders = catalog.list_folders('saved')
    assert len(SAVED_CATEGORY_FOLDERS) == len(folders) == 9
    assert {f['folder_id']: f['name'] for f in folders} == {
        SAVED_FOLDER_IDS[cat]: name for cat, name in SAVED_CATEGORY_FOLDERS.items()
    }
    assert catalog.list_folders('shared') == []
    assert catalog.resolve_folder('saved', 'Script Files') == 'saved:script_files'
    assert catalog.resolve_folder('saved', 'Job Files') == 'saved:job_files'
    for invalid in ('saved:script_file', 'saved:job_file', 'saved:script_output', 'saved:job_output'):
        with pytest.raises((KeyError, ValueError)):
            catalog.resolve_folder('saved', invalid)


@pytest.mark.parametrize('value,expected', [
    ('ScReEnShOtS', 'screenshots'), ('SCRIPT_FILES', 'script_files'),
    ('JOB_FILES', 'job_files'), ('  CLIPBOARD  ', 'clipboard'),
    ('download', 'inbox'), ('script_file', 'inbox'), ('', 'inbox'),
    (None, 'inbox'), ('not_an_artifact_category', 'inbox'),
])
def test_category_input_is_case_insensitive_and_other_values_become_inbox(value, expected):
    assert normalize_saved_category(value).value == expected
    assert classify_artifact('files', value) == ('saved', expected, f'saved:{expected}')


def test_saved_only_stores_category_and_derives_the_single_folder(tmp_path):
    c = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    item = make_record(tmp_path / 'general.txt', 'general', category='ScReEnShots', folder_id=None)
    saved = c.save(item)
    assert saved['category'] == 'screenshots'
    assert saved['folder_id'] == 'saved:screenshots'
    assert c.get('general') == saved
    assert [item['artifact_id'] for item in c.list(scope='saved', category='SCREENSHOTS')] == ['general']
    assert [item['artifact_id'] for item in c.list(folder_id='saved:screenshots')] == ['general']
    with sqlite3.connect(c.database.db_path) as conn:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(artifact_entries)')}
        assert 'category' in columns and 'source_kind' not in columns
        folder_id, category, raw = conn.execute(
            'SELECT folder_id, category, payload_json FROM artifact_entries WHERE artifact_id=?',
            ('general',)).fetchone()
    assert folder_id is None and category == 'screenshots'
    assert 'folder_id' not in json.loads(raw)
    assert json.loads(raw)['category'] == 'screenshots'
    bad = make_record(tmp_path / 'bad.txt', 'bad', category='screenshots', folder_id='saved:downloads')
    with pytest.raises(ValueError, match='must match category'):
        c.save(bad)
    assert c.get('bad') is None
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.move('general', 'saved:downloads')


def test_shared_records_have_no_category_and_only_their_own_folder(tmp_path):
    c = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    team = c.create_folder('shared', 'Team')
    first = c.create_folder('shared', 'One', team['folder_id'])
    second = c.create_folder('shared', 'Two', team['folder_id'])
    item = make_record(tmp_path / 'shared.bin', 'shared-one', scope='shared', folder_id=first['folder_id'])
    saved = c.save(item)
    assert 'category' not in saved
    assert saved['folder_id'] == first['folder_id']
    moved = c.move('shared-one', second['folder_id'])
    assert 'category' not in moved
    assert moved['folder_id'] == second['folder_id']
    with sqlite3.connect(c.database.db_path) as conn:
        assert conn.execute('SELECT category FROM artifact_entries WHERE artifact_id=?',
                            ('shared-one',)).fetchone()[0] is None
    bad = dict(item, artifact_id='bad', category='inbox')
    with pytest.raises(ValueError, match='Only Saved Files'):
        c.save(bad)
    with pytest.raises(ValueError, match='empty'):
        c.delete_folder(second['folder_id'])
    c.rename_folder(second['folder_id'], 'Renamed')
    c.delete('shared-one')
    assert (tmp_path / 'shared.bin').exists()
    c.delete_folder(second['folder_id'])


def test_preview_is_not_saved_and_does_not_have_category(tmp_path):
    c = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    c.save(make_record(tmp_path / 'a.txt', 'a'))
    c.save(make_record(tmp_path / 'b.txt', 'b', scope='preview', folder_id=None))
    assert [a['artifact_id'] for a in c.list()] == ['a']
    assert [a['artifact_id'] for a in c.list(scope='preview')] == ['b']
    assert 'category' not in c.get('b')
    assert classify_artifact('shared_files') == ('shared', None, None)
    assert classify_artifact('previews') == ('preview', None, None)
    with pytest.raises(ValueError, match='Only Saved Files'):
        c.list(scope='shared', category='screenshots')


def test_import_atomic_and_rejects_old_top_level_source_kind(tmp_path):
    c = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    one = make_record(tmp_path / 'one.txt', 'one')
    two = make_record(tmp_path / 'two.txt', 'two', folder_id='saved:downloads')
    with pytest.raises(ValueError, match='must match category'):
        c.import_records([one, two])
    assert c.get('one') is None
    assert c.get('two') is None
    obsolete = dict(one, source_kind='screenshots')
    with pytest.raises(ValueError, match='Obsolete'):
        c.save(obsolete)


def test_import_shared_and_preview_records_with_null_category(tmp_path):
    c = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    shared_folder = c.create_folder('shared', 'Team')
    shared = make_record(tmp_path / 'shared-import.txt', 'shared-import', scope='shared', folder_id=shared_folder['folder_id'])
    preview = make_record(tmp_path / 'preview-import.txt', 'preview-import', scope='preview', folder_id=None)
    imported, already = c.import_records([shared, preview])
    assert (imported, already) == (2, 0)
    assert 'category' not in c.get('shared-import')
    assert c.get('shared-import')['folder_id'] == shared_folder['folder_id']
    assert 'category' not in c.get('preview-import')
    with sqlite3.connect(c.database.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM artifact_entries WHERE category IS NOT NULL').fetchone()[0] == 0
    assert c.import_records([shared, preview]) == (0, 2)


def test_old_database_schema_requires_explicit_reset(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.close_thread_connection()
    with sqlite3.connect(path) as conn:
        conn.execute('ALTER TABLE artifact_entries ADD COLUMN source_kind TEXT')
    with pytest.raises(RuntimeError, match='incompatible schema for artifact_entries'):
        RchDatabase(str(path))
    with sqlite3.connect(path) as conn:
        assert 'source_kind' in {r[1] for r in conn.execute('PRAGMA table_info(artifact_entries)')}


def test_shared_folder_management_guards(tmp_path):
    c = ArtifactSqliteCatalog(RchDatabase(str(tmp_path / 'rch.db')))
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.create_folder('saved', 'Project A')
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.rename_folder('saved:downloads', 'New Label')
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.delete_folder('saved:downloads')
    folder = c.create_folder('shared', 'Project A')
    with pytest.raises(ValueError, match='already exists'):
        c.create_folder('shared', 'project a')
    with pytest.raises(ValueError, match='Unknown'):
        c.resolve_folder('saved', 'Project A')
    with pytest.raises(ValueError, match='Unknown'):
        c.resolve_folder('shared', 'Other')
    assert c.get_folder(folder['folder_id'])['name'] == 'Project A'
