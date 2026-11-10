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
        'Screenshots', 'Webcam', 'Downloads', 'Clipboard', 'Script Files',
        'Job Files', 'Command Output', 'Terminal Logs', 'Inbox',
    }
    assert len(names) == 9
    assert catalog.list_folders('shared') == []
    shared_folder = catalog.create_folder('shared', 'Team')
    item = make_record(tmp_path / 'image.png', 'id-1')
    catalog.save(item)
    with pytest.raises(ValueError, match='Only Shared Files'):
        catalog.move('id-1', shared_folder['folder_id'])
    assert catalog.get('id-1')['folder_id'] == 'saved:screenshots'


def test_shared_folder_hierarchy_and_fixed_saved_folders(tmp_path):
    c = ArtifactSqliteCatalog(str(tmp_path / 'artifact.db'))
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.create_folder('saved', 'Project A')
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.rename_folder('saved:downloads', 'New label')
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.delete_folder('saved:downloads')
    parent = c.create_folder('shared', 'Project A')
    child = c.create_folder('shared', 'Docs', parent['folder_id'])
    c.create_folder('shared', 'Docs')  # same label under another parent
    with pytest.raises(ValueError, match='already exists'):
        c.create_folder('shared', 'docs', parent['folder_id'])
    file_path = tmp_path / 'payload.txt'
    c.save(make_record(file_path, 'artifact-x', 'shared', 'shared_upload', None))
    c.move('artifact-x', child['folder_id'])
    assert c.get('artifact-x')['folder_id'] == child['folder_id']
    assert file_path.read_text() == 'untouched content'
    with pytest.raises(ValueError, match='empty'):
        c.delete_folder(child['folder_id'])
    c.rename_folder(child['folder_id'], 'Documents')
    assert c.get_folder(child['folder_id'])['name'] == 'Documents'
    c.delete('artifact-x')
    assert file_path.exists()  # physical content is not deleted by catalog alone
    c.delete_folder(child['folder_id'])


def test_saved_uses_single_source_kind_and_rejects_any_move(tmp_path):
    import sqlite3
    c = ArtifactSqliteCatalog(str(tmp_path / 'db.sqlite3'))
    item = make_record(tmp_path / 'general.txt', 'general', source_kind='inbox', folder_id=None)
    assert c.save(item)['folder_id'] == 'saved:inbox'
    assert c.list(scope='saved', folder_id='saved:inbox')[0]['artifact_id'] == 'general'
    assert c.list(folder_id='saved:inbox')[0]['artifact_id'] == 'general'
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.move('general', 'saved:screenshots')
    with pytest.raises(ValueError, match='Only Shared Files'):
        c.move('general', '')
    with sqlite3.connect(c.db_path) as conn:
        stored_folder, stored_kind, raw = conn.execute(
            'SELECT folder_id, source_kind, payload_json FROM artifact_entries WHERE artifact_id=?',
            ('general',)).fetchone()
    assert stored_folder is None and stored_kind == 'inbox'
    assert 'folder_id' not in json.loads(raw)
    bad = make_record(tmp_path / 'bad.txt', 'bad', folder_id='arbitrary-folder')
    with pytest.raises(ValueError, match='must match source_kind'):
        c.save(bad)
    assert c.get('bad') is None


def test_existing_saved_custom_folders_are_retired_without_losing_files(tmp_path):
    import sqlite3
    db_path = tmp_path / 'artifact.db'
    c = ArtifactSqliteCatalog(str(db_path))
    custom = make_record(tmp_path / 'screenshot.png', 'old-screenshot')
    c.save(custom)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO artifact_folders VALUES ('old-custom', 'saved', NULL, 'Custom', 0, '2026-11-10')")
        conn.execute("INSERT INTO artifact_folders VALUES ('old-child', 'saved', 'old-custom', 'Child', 0, '2026-11-10')")
        raw = c.get('old-screenshot')
        raw['folder_id'] = 'old-child'
        conn.execute('UPDATE artifact_entries SET folder_id=?, payload_json=? WHERE artifact_id=?',
                     ('old-child', json.dumps(raw), 'old-screenshot'))
    reopened = ArtifactSqliteCatalog(str(db_path))
    assert reopened.get('old-screenshot')['folder_id'] == 'saved:screenshots'
    assert reopened.get('old-screenshot')['artifact_id'] == 'old-screenshot'
    assert (tmp_path / 'screenshot.png').read_text() == 'untouched content'
    assert len(reopened.list_folders('saved')) == 9
    assert reopened.get_folder('saved:inbox')['name'] == 'Inbox'
    with pytest.raises(FileNotFoundError):
        reopened.get_folder('old-custom')
    with pytest.raises(FileNotFoundError):
        reopened.get_folder('old-child')


def test_source_classification_and_preview_is_not_in_saved_all_files(tmp_path):
    cases = [
        ('files', 'screenshot', {}, 'screenshots'),
        ('files', 'webcam', {}, 'webcam'),
        ('files', 'download', {}, 'downloads'),
        ('files', 'clipboard_image', {}, 'clipboard'),
        ('files', 'script', {}, 'script_file'),
        ('command_output', 'job_output', {}, 'command_output'),
        ('command_output', 'command_output', {}, 'command_output'),
        ('command_output', 'command_output', {'source': 'terminal_toolbar_action'}, 'terminal_logs'),
        ('command_output', 'command_output', {'source': 'pty_toolbar_action'}, 'terminal_logs'),
        ('files', 'other', {}, 'inbox'),
        ('files', '', {}, 'inbox'),
    ]
    for t, category, extra, expected in cases:
        assert classify_artifact(t, category, extra) == ('saved', expected,
            f'saved:{expected}')
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
    with pytest.raises(ValueError, match='must match source_kind'):
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


def test_canonical_saved_ids_and_sources_are_strict(tmp_path):
    c = ArtifactSqliteCatalog(str(tmp_path / 'catalog.sqlite3'))
    assert c.resolve_folder('saved', 'Script Files') == 'saved:script_file'
    assert c.resolve_folder('saved', 'Job Files') == 'saved:job_file'
    for old_id in ('saved:script_output', 'saved:job_output'):
        with pytest.raises((KeyError, ValueError)):
            c.resolve_folder('saved', old_id)
    assert classify_artifact('command_output', 'job_output') == (
        'saved', 'command_output', 'saved:command_output')
    with pytest.raises(ValueError, match='Unknown artifact producer category'):
        classify_artifact('files', 'unknown-producer')
    bad = make_record(tmp_path / 'bad-artifact', 'invalid', source_kind='script_output', folder_id=None)
    with pytest.raises(ValueError):
        c.save(bad)


def test_shared_source_and_folder_remain_independent(tmp_path):
    c = ArtifactSqliteCatalog(str(tmp_path / 'db.sqlite3'))
    parent = c.create_folder('shared', 'Team')
    first = c.create_folder('shared', 'One', parent['folder_id'])
    second = c.create_folder('shared', 'Two', parent['folder_id'])
    item = make_record(tmp_path / 'shared.bin', 'shared-one', scope='shared',
                       source_kind='shared_upload', folder_id=first['folder_id'])
    c.save(item)
    moved = c.move('shared-one', second['folder_id'])
    assert moved['source_kind'] == 'shared_upload'
    assert moved['folder_id'] == second['folder_id']
    assert (tmp_path / 'shared.bin').is_file()


def test_old_saved_folder_display_name_does_not_block_canonical_id(tmp_path):
    """Existing Script Files labels cannot shadow the new script_file ID."""
    import sqlite3
    db = tmp_path / 'catalog.sqlite3'
    catalog = ArtifactSqliteCatalog(str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM artifact_folders WHERE folder_id='saved:script_file'")
        conn.execute("INSERT INTO artifact_folders VALUES (?, 'saved', NULL, 'Script Files', 1, ?)",
                     ('saved:script_output', '2026-11-10'))
    reopened = ArtifactSqliteCatalog(str(db))
    assert reopened.get_folder('saved:script_file')['name'] == 'Script Files'
    with pytest.raises(FileNotFoundError):
        reopened.get_folder('saved:script_output')
    assert len(reopened.list_folders('saved')) == 9
