"""Server-wide preferences persist and apply to subsequent text reads."""

import pytest

from server.application.preferences.server_preferences import ServerPreferences
from server.application.documents.document_library_service import DocumentLibraryService
from server.persistence.rch_database import RchDatabase


@pytest.fixture
def preferences(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    yield ServerPreferences(database)
    database.close_thread_connection()


def test_server_preference_defaults(preferences):
    assert preferences.read() == {
        'ask_on_conflict': False,
        'preview_text_max_bytes': 524288,
        'log_viewer_max_chars': 524288,
    }


def test_server_preferences_persist_and_reload(preferences):
    expected = {
        'ask_on_conflict': True,
        'preview_text_max_bytes': 1024 * 1024,
        'log_viewer_max_chars': 128 * 1024,
    }
    assert preferences.save(expected) == expected
    assert preferences.read() == expected
    assert ServerPreferences(preferences.store.database).read() == expected


@pytest.mark.parametrize('invalid', [
    {'ask_on_conflict': 'yes'},
    {'preview_text_max_bytes': 65535},
    {'preview_text_max_bytes': 8388609},
    {'log_viewer_max_chars': 2.5},
    {'log_viewer_max_chars': True},
])
def test_server_preferences_reject_invalid_types_and_ranges(preferences, invalid):
    payload = preferences.read()
    payload.update(invalid)
    with pytest.raises(ValueError):
        preferences.save(payload)
    assert preferences.read()['ask_on_conflict'] is False


def test_server_preferences_require_current_fields(preferences):
    with pytest.raises(ValueError, match='All Server preference fields'):
        preferences.save({'ask_on_conflict': True})


def test_document_editor_reads_updated_server_limit(preferences, tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    filename = root / 'large.md'
    filename.write_bytes(b'x' * (70 * 1024))
    library = DocumentLibraryService({'notes': {'path': str(root)}},
                                     lambda: preferences.read()['preview_text_max_bytes'])
    payload = preferences.read()
    payload['preview_text_max_bytes'] = 64 * 1024
    preferences.save(payload)
    with pytest.raises(ValueError, match='exceeds the edit size limit'):
        library.read_document('notes', 'large.md')
    payload['preview_text_max_bytes'] = 128 * 1024
    preferences.save(payload)
    assert len(library.read_document('notes', 'large.md')['content']) == 70 * 1024
