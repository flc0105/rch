"""Artifact Saved category and Shared folder end-to-end contract."""
import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip('werkzeug', reason='Artifact Web integration requires Werkzeug')

from core.artifact_contract import (
    ArtifactCategory, ArtifactType, SAVED_FOLDER_IDS,
)
from server.application.artifact.artifact_registry_service import ArtifactRegistryService
from server.application.artifact.artifact_service import WebArtifactService
from server.persistence.rch_database import RchDatabase
from server.application.web.artifact_api import WebArtifactApi


class Upload:
    filename = 'example.txt'

    def save(self, destination, buffer_size=None):
        Path(destination).write_text('Canonical artifact test', encoding='utf-8')


def api_for(tmp_path):
    service = WebArtifactService.__new__(WebArtifactService)
    service.database = RchDatabase(str(tmp_path / 'rch.db'))
    service.artifacts_root_dir = str(tmp_path / 'artifacts')
    service.previews_dir = str(tmp_path / 'artifacts' / 'preview')
    service.registry_service = ArtifactRegistryService(service)
    return WebArtifactApi(None, None, service), service.registry_service.catalog


@pytest.mark.parametrize('category,expected', [
    ('screenshots', 'screenshots'), ('ScReenShots', 'screenshots'),
    ('SCRIPT_FILES', 'script_files'), ('job_files', 'job_files'),
    ('clipboard', 'clipboard'), ('webcam', 'webcam'), ('downloads', 'downloads'),
    ('saved', 'saved'), ('terminal_logs', 'terminal_logs'),
    ('inbox', 'inbox'), ('script_file', 'inbox'), ('random', 'inbox'),
    ('', 'inbox'), (None, 'inbox'),
])
def test_upload_category_is_the_only_saved_folder_source(tmp_path, category, expected):
    api, catalog = api_for(tmp_path)
    item = api.save_http_uploaded_file(Upload(), artifact_type='saved', category=category)
    assert item['scope'] == ArtifactType.SAVED.value
    assert item['category'] == expected
    assert item['folder_id'] == f'saved:{expected}'
    assert catalog.list(scope='saved', category=expected)[0]['artifact_id'] == item['artifact_id']
    with sqlite3.connect(catalog.database.db_path) as conn:
        folder_id, db_category, raw = conn.execute('SELECT folder_id, category, payload_json FROM artifact_entries WHERE artifact_id=?',
                                                  (item['artifact_id'],)).fetchone()
    assert folder_id is None and db_category == expected
    assert 'folder_id' not in json.loads(raw)
    assert Path(item['saved_path']).exists()
    with pytest.raises(ValueError, match='Only Shared Files'):
        api.move_artifact(item['artifact_id'], SAVED_FOLDER_IDS[ArtifactCategory.DOWNLOADS])


def test_shared_upload_has_folder_but_no_category(tmp_path):
    api, catalog = api_for(tmp_path)
    first = catalog.create_folder('shared', 'First')
    second = catalog.create_folder('shared', 'Second')
    item = api.save_http_uploaded_file(Upload(), artifact_type='shared', folder_id=first['folder_id'])
    assert item['scope'] == 'shared'
    assert 'category' not in item
    assert item['folder_id'] == first['folder_id']
    assert not item.get('extra') or 'source_kind' not in item['extra']
    moved = api.move_artifact(item['artifact_id'], second['folder_id'])
    assert 'category' not in moved
    assert moved['folder_id'] == second['folder_id']
    with sqlite3.connect(catalog.database.db_path) as conn:
        assert conn.execute('SELECT category FROM artifact_entries WHERE artifact_id=?',
                            (item['artifact_id'],)).fetchone()[0] is None
    assert Path(item['saved_path']).exists()


def test_api_rejects_shared_category_even_if_empty_and_saved_folder(tmp_path):
    api, catalog = api_for(tmp_path)
    for category in ('', 'screenshots', 'InBoX'):
        with pytest.raises(ValueError, match='Only Saved Files'):
            api.save_http_uploaded_file(Upload(), artifact_type='shared', category=category)
    with pytest.raises(ValueError, match='Saved Files uploads use category'):
        api.save_http_uploaded_file(Upload(), folder='Screenshots')
    with pytest.raises(ValueError, match='Saved Files uploads use category'):
        api.save_http_uploaded_file(Upload(), folder_id='saved:screenshots')
    assert catalog.list() == []
    assert not (tmp_path / 'artifacts' / 'objects').exists()


def test_preview_saved_into_selected_category_folder(tmp_path):
    api, catalog = api_for(tmp_path)
    preview = api.save_http_uploaded_file(Upload(), artifact_type='preview')
    assert 'category' not in preview
    saved = api.artifact_service.registry_service.save_preview_to_saved(
        preview['artifact_id'], 'saved:script_files')
    assert saved['category'] == 'script_files'
    assert saved['folder_id'] == 'saved:script_files'
    assert catalog.get(saved['artifact_id'])['category'] == 'script_files'
    assert catalog.get(preview['artifact_id']).get('category') is None
    default = api.artifact_service.registry_service.save_preview_to_saved(preview['artifact_id'])
    assert default['category'] == 'downloads'
    assert default['folder_id'] == 'saved:downloads'


def test_scope_type_and_category_enum_are_closed(tmp_path):
    assert ArtifactType(ArtifactType.SAVED) == ArtifactType.SAVED
    with pytest.raises(ValueError):
        ArtifactType('bogus')
    with pytest.raises(ValueError):
        ArtifactCategory('script_file')
