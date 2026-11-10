"""Saved has a single classification; Shared retains an independent folder."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('werkzeug', reason='Artifact Web integration requires Werkzeug')

from core.artifact_contract import (
    ArtifactScope, ArtifactSourceKind, ArtifactType, SAVED_FOLDER_IDS, scope_for_type,
)
from server.application.artifact.artifact_registry_service import ArtifactRegistryService
from server.application.artifact.artifact_service import WebArtifactService
from server.application.web.artifact_api import WebArtifactApi


class Upload:
    filename = 'example.txt'

    def save(self, destination, buffer_size=None):
        Path(destination).write_text('RCH canonical artifact test', encoding='utf-8')


def api_for(tmp_path):
    service = WebArtifactService.__new__(WebArtifactService)
    service.artifacts_root_dir = str(tmp_path / 'artifacts')
    service.previews_dir = str(tmp_path / 'artifacts' / 'previews')
    service.registry_service = ArtifactRegistryService(service)
    return WebArtifactApi(None, None, service), service.registry_service.catalog


def test_folder_selection_replaces_sdk_origin_for_saved_before_persist(tmp_path):
    api, catalog = api_for(tmp_path)
    item = api.save_http_uploaded_file(
        Upload(), artifact_type=ArtifactType.FILES.value,
        source_kind=ArtifactSourceKind.SCRIPT_FILE.value, folder='Screenshots')
    assert item['scope'] == ArtifactScope.SAVED.value
    assert item['source_kind'] == ArtifactSourceKind.SCREENSHOTS.value
    assert item['folder_id'] == SAVED_FOLDER_IDS[ArtifactSourceKind.SCREENSHOTS]
    assert catalog.list(scope=ArtifactScope.SAVED.value, folder_id=item['folder_id'])[0]['artifact_id'] == item['artifact_id']
    with sqlite3.connect(catalog.db_path) as conn:
        folder_id, json_data = conn.execute(
            'SELECT folder_id, payload_json FROM artifact_entries WHERE artifact_id=?',
            (item['artifact_id'],)).fetchone()
    assert folder_id is None
    assert 'folder_id' not in json.loads(json_data)
    assert Path(item['saved_path']).exists()
    with pytest.raises(ValueError, match='Only Shared Files'):
        api.move_artifact(item['artifact_id'], SAVED_FOLDER_IDS[ArtifactSourceKind.DOWNLOADS])


def test_shared_upload_keeps_source_and_can_move_to_another_folder(tmp_path):
    api, catalog = api_for(tmp_path)
    first = catalog.create_folder(ArtifactScope.SHARED.value, 'First')
    second = catalog.create_folder(ArtifactScope.SHARED.value, 'Second')
    item = api.save_http_uploaded_file(Upload(), artifact_type=ArtifactType.SHARED_FILES.value,
                                       source_kind=ArtifactSourceKind.SHARED_UPLOAD.value,
                                       folder_id=first['folder_id'])
    assert item['source_kind'] == ArtifactSourceKind.SHARED_UPLOAD.value
    assert item['folder_id'] == first['folder_id']
    moved = api.move_artifact(item['artifact_id'], second['folder_id'])
    assert moved['source_kind'] == ArtifactSourceKind.SHARED_UPLOAD.value
    assert moved['folder_id'] == second['folder_id']
    assert Path(item['saved_path']).exists()


def test_invalid_saved_folder_is_rejected_before_file_write(tmp_path):
    api, catalog = api_for(tmp_path)
    upload = Upload()
    with pytest.raises(ValueError):
        api.save_http_uploaded_file(upload, source_kind=ArtifactSourceKind.SCRIPT_FILE.value,
                                    folder='Not a real folder')
    with pytest.raises(ValueError, match='Unknown artifact producer category'):
        api.save_http_uploaded_file(upload, source_kind='invalid-kind')
    assert catalog.list() == []
    assert not (tmp_path / 'artifacts' / 'objects').exists()


def test_canonical_scope_and_kind_are_closed_sets():
    assert scope_for_type(ArtifactType.COMMAND_OUTPUT) == ArtifactScope.SAVED
    with pytest.raises(ValueError):
        scope_for_type('not_an_artifact_type')
    with pytest.raises(ValueError):
        ArtifactSourceKind('script_output')
