import json
from pathlib import Path

import pytest

from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog, classify_artifact


def make_record(path, artifact_id, scope='saved', source_kind='screenshots', folder_id='saved:screenshots'):
    path.write_text('untouched content', encoding='utf-8')
    return {
        'artifact_id': artifact_id, 'scope': scope, 'source_kind': source_kind,
        'folder_id': folder_id, 'machine_id': 'machine-one', 'saved_path': str(path),
        'original_name': 'Original.txt', 'stored_name': path.name,
        'created_at': '2026-11-10 09:00:00',
    }


def test_default_folders_and_cross_scope_move_guards(tmp_path):
    catalog = ArtifactSqliteCatalog(str(tmp_path / 'artifacts.db'))
    names = [folder['name'] for folder in catalog.list_folders('saved')]
    assert names == sorted(names, key=str.casefold) or set(names) == {
        'Screenshots', 'Webcam', 'Downloads', 'Clipboard', 'Script Output',
        'Job Output', 'Command Output', 'Terminal Logs', 'Inbox',
    }
    assert len(names) == 9
    assert catalog.list_folders('shared') == []
    shared_folder = catalog.create_folder('shared', 'Team')
    item = make_record(tmp_path / 'image.png', 'id-1')
    catalog.save(item)
    with pytest.raises(ValueError, match='sharing scope'):
        catalog.move('id-1', shared_folder['folder_id'])
    assert catalog.get('id-1')['folder_id'] == 'saved:screenshots'


def test_folder_hierarchy_name_collision_and_move_only_updates_database(tmp_path):
    c = ArtifactSqliteCatalog(str(tmp_path / 'artifact.db'))
    parent = c.create_folder('saved', 'Project A')
    child = c.create_folder('saved', 'Docs', parent['folder_id'])
    c.create_folder('saved', 'Docs')  # identical name under a different parent is legal
    with pytest.raises(ValueError, match='already exists'):
        c.create_folder('saved', 'docs', parent['folder_id'])
    file_path = tmp_path / 'payload.txt'
    c.save(make_record(file_path, 'artifact-x'))
    c.move('artifact-x', child['folder_id'])
    assert c.get('artifact-x')['folder_id'] == child['folder_id']
    assert file_path.read_text() == 'untouched content'
    with pytest.raises(ValueError, match='empty'):
        c.delete_folder(child['folder_id'])
    c.rename_folder(child['folder_id'], 'Documents')
    assert c.get_folder(child['folder_id'])['name'] == 'Documents'
    c.delete('artifact-x')
    assert file_path.exists()  # DB index deletion does not silently delete file bytes
    c.delete_folder(child['folder_id'])
    with pytest.raises(ValueError, match='Preset'):
        c.rename_folder('saved:downloads', 'New label')


def test_source_classification_and_preview_is_not_in_saved_all_files(tmp_path):
    cases = [
        ('files', 'screenshot', {}, 'screenshots'),
        ('files', 'webcam', {}, 'webcam'),
        ('files', 'download', {}, 'downloads'),
        ('files', 'clipboard_image', {}, 'clipboard'),
        ('files', 'script', {}, 'script_output'),
        ('command_output', 'job_output', {}, 'job_output'),
        ('command_output', 'command_output', {}, 'command_output'),
        ('command_output', 'command_output', {'source': 'terminal_toolbar_action'}, 'terminal_logs'),
        ('command_output', 'command_output', {'source': 'pty_toolbar_action'}, 'terminal_logs'),
        ('files', 'other', {}, 'inbox'),
    ]
    for t, category, extra, expected in cases:
        assert classify_artifact(t, category, extra) == ('saved', expected, f'saved:{expected}')
    assert classify_artifact('shared_files', '', {})[:2] == ('shared', 'shared_upload')
    assert classify_artifact('previews', '', {})[:2] == ('preview', 'preview_cache')
    c = ArtifactSqliteCatalog(str(tmp_path / 'db.sqlite3'))
    c.save(make_record(tmp_path / 'a.txt', 'a'))
    c.save(make_record(tmp_path / 'b.txt', 'b', 'preview', 'preview_cache', None))
    assert [a['artifact_id'] for a in c.list()] == ['a']
    assert [a['artifact_id'] for a in c.list(scope='preview')] == ['b']
    assert [a['artifact_id'] for a in c.list(scope='saved', source_kind='screenshots')] == ['a']


def test_one_time_import_preserves_id_and_original_file(tmp_path):
    from scripts.migrate_artifact_metadata import migrate
    root = tmp_path / 'artifacts'
    sidecar_dir = root / 'files' / 'screenshots' / 'machine-one' / 'meta'
    sidecar_dir.mkdir(parents=True)
    image = sidecar_dir.parent / 'shot.png'
    image.write_bytes(b'PNG contents')
    sidecar = sidecar_dir / 'shot.png.meta.json'
    sidecar.write_text(json.dumps({
        'artifact_id': 'original-id', 'artifact_type': 'files', 'category': 'screenshot',
        'saved_path': str(image), 'created_at': '2026-11-10 11:00:00',
        'original_name': 'shot.png', 'stored_name': 'shot.png', 'machine_id': 'machine-one',
    }))
    assert migrate(root, False, False)['imported'] == 1
    assert not (root / 'catalog.sqlite3').exists()
    assert migrate(root, True, False)['imported'] == 1
    c = ArtifactSqliteCatalog(str(root / 'catalog.sqlite3'))
    assert c.get('original-id')['folder_id'] == 'saved:screenshots'
    assert c.get('original-id')['saved_path'] == str(image)
    assert migrate(root, True, False)['already_in_db'] == 1
    assert migrate(root, True, True)['removed_sidecars'] == 1
    assert not sidecar.exists()
    assert image.exists() and image.read_bytes() == b'PNG contents'


def test_bulk_import_is_transactional_on_folder_conflict(tmp_path):
    c = ArtifactSqliteCatalog(str(tmp_path / 'db.sqlite3'))
    one = make_record(tmp_path / 'one.txt', 'one')
    two = make_record(tmp_path / 'two.txt', 'two')
    two['folder_id'] = 'nonexistent-folder'
    with pytest.raises(ValueError, match='Invalid folder'):
        c.import_records([one, two])
    assert c.get('one') is None
    assert c.get('two') is None


def test_storage_uses_normalized_source_and_folder_without_duplicate_category(tmp_path):
    catalog = ArtifactSqliteCatalog(str(tmp_path / 'artifact.db'))
    record = make_record(tmp_path / 'file.txt', 'id-uncategorized')
    record['category'] = 'screenshot'
    record['_meta_path'] = '/legacy/sidecar.json'
    catalog.save(record)
    stored = catalog.get('id-uncategorized')
    assert stored['source_kind'] == 'screenshots'
    assert stored['folder_id'] == 'saved:screenshots'
    assert 'category' not in stored
    assert '_meta_path' not in stored
    import sqlite3, json
    with sqlite3.connect(catalog.db_path) as conn:
        raw = json.loads(conn.execute('SELECT payload_json FROM artifact_entries WHERE artifact_id=?',
                                      ('id-uncategorized',)).fetchone()[0])
    assert 'category' not in raw
    assert '_meta_path' not in raw


def test_saved_files_cannot_be_manually_created_through_shared_create_endpoint(tmp_path):
    from server.application.web.artifact_api import WebArtifactApi
    api = WebArtifactApi(server=None, event_bus=None, artifact_service=None)
    with pytest.raises(ValueError, match='only available in Shared Files'):
        api.create_file('saved', 'no-machine.txt')
