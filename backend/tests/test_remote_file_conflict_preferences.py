"""Shared global file conflict preference and Browser API contracts."""
import sqlite3
from types import SimpleNamespace

import pytest
from server.application.preferences.settings_store import SettingsStore


class Database:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE settings (namespace TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at_ms INTEGER NOT NULL)')

    def connection(self):
        return self.db


def test_shared_settings_store_persists_default_on_off():
    db = Database()
    store = SettingsStore(db, 'remote_file_conflicts')
    assert store.read() == {}
    store.write({'ask_on_conflict': True})
    assert SettingsStore(db, 'remote_file_conflicts').read()['ask_on_conflict'] is True
    store.write({'ask_on_conflict': False})
    assert store.read()['ask_on_conflict'] is False


def test_preferences_default_off_and_persist_across_requests():
    Flask = pytest.importorskip('flask').Flask
    from server.web.routes.remote_files import create_remote_files_blueprint
    db = Database()
    mock = SimpleNamespace(database=db, web_service=SimpleNamespace(remote_file_api=object()))
    app = Flask(__name__)
    app.register_blueprint(create_remote_files_blueprint(mock))
    client = app.test_client()
    endpoint = '/api/remote-files/conflict-preferences'

    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.get_json()['data'] == {'ask_on_conflict': False}
    assert client.put(endpoint, json={'ask_on_conflict': 'yes'}).status_code == 400
    assert client.put(endpoint, json={'ask_on_conflict': True}).get_json()['data'] == {'ask_on_conflict': True}
    assert client.get(endpoint).get_json()['data'] == {'ask_on_conflict': True}
    assert SettingsStore(db, 'remote_file_conflicts').read() == {'ask_on_conflict': True}
    assert client.put(endpoint, json={'ask_on_conflict': False}).get_json()['data'] == {'ask_on_conflict': False}
