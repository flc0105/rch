"""Regression: Command Output is a Saved category, never a Saved artifact type."""

import json

import pytest

from core.artifact_contract import (
    ArtifactCategory,
    SAVED_CATEGORY_FOLDERS,
    classify_artifact,
    normalize_saved_category,
    saved_folder_id,
)
from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.persistence.rch_database import RchDatabase


@pytest.mark.parametrize('category', [member.value for member in ArtifactCategory])
def test_all_nine_saved_categories_roundtrip_to_correct_virtual_folder(category):
    assert len(SAVED_CATEGORY_FOLDERS) == 9
    assert classify_artifact('saved', category) == ('saved', category, f'saved:{category}')
    assert normalize_saved_category(category.upper()).value == category
    assert saved_folder_id(category) == f'saved:{category}'


def test_artifact_type_does_not_become_saved_category():
    assert ArtifactCategory.COMMAND_OUTPUT.value == 'command_output'
    assert classify_artifact('saved', 'saved') == ('saved', 'inbox', 'saved:inbox')


def test_existing_command_output_in_rch_db_can_be_listed_on_startup(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    catalog = ArtifactSqliteCatalog(database, tmp_path / 'artifacts')
    with database.transaction() as conn:
        conn.execute(
            '''INSERT INTO artifact_entries
               (artifact_id, artifact_type, folder_id, original_name, size,
                category, machine_id, saved_at, saved_path, client_id,
                source_command_id, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            ('d0' * 16, 'saved', None, 'result.txt', 7,
             'command_output', 'machine-1', '2026-11-11 16:09:56',
             'objects/d0/' + ('d0' * 16), 'client-1', None, json.dumps({'saved_from': 'saveout'})),
        )
    try:
        items = catalog.list()
        assert len(items) == 1
        assert items[0]['category'] == 'command_output'
        assert items[0]['folder_id'] == 'saved:command_output'
        assert catalog.list(category='command_output') == items
        assert catalog.list(folder_id='saved:command_output') == items
    finally:
        database.close_thread_connection()
