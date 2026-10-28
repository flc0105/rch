"""Tests for Server-global Terminal Connection Context preferences."""

import tempfile
import unittest
from pathlib import Path

from server.application.preferences.terminal_context_preference_store import (
    ALLOWED_TERMINAL_CONTEXT_FIELD_IDS,
    TerminalContextPreferenceStore,
)
from server.application.web.terminal_context_preferences_api import WebTerminalContextPreferencesApi
from server.persistence.rch_database import RchDatabase


class TerminalContextPreferenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = RchDatabase(str(Path(self.tmp.name) / 'rch.db'))
        self.store = TerminalContextPreferenceStore(self.database)

    def tearDown(self):
        self.database.close_thread_connection()
        self.tmp.cleanup()

    def test_defaults_to_no_displayed_fields(self):
        self.assertEqual(self.store.get_preferences(), {'field_ids': []})

    def test_save_keeps_known_fields_in_user_order_and_removes_duplicates(self):
        saved = self.store.save_preferences({
            'field_ids': ['pid', 'status', 'pid', 'reported_jobs', 'command_count', 'launch_mode'],
        })

        self.assertEqual(saved, {'field_ids': ['pid', 'status', 'launch_mode']})
        self.assertTrue(set(saved['field_ids']).issubset(ALLOWED_TERMINAL_CONTEXT_FIELD_IDS))

    def test_preferences_are_global_and_persisted_in_settings_namespace(self):
        self.store.save_preferences({'field_ids': ['integrity', 'pid']})
        self.database.close_thread_connection()

        reloaded = TerminalContextPreferenceStore(self.database)
        self.assertEqual(reloaded.get_preferences(), {'field_ids': ['integrity', 'pid']})
        row = self.database.connection().execute(
            "SELECT value_json FROM settings WHERE namespace = ?",
            ('terminal_context_preferences',),
        ).fetchone()
        self.assertIsNotNone(row)

    def test_task_selection_survives_save_and_reload(self):
        saved = self.store.save_preferences({'field_ids': ['status', 'task', 'pid']})
        self.assertEqual(saved, {'field_ids': ['status', 'task', 'pid']})
        self.database.close_thread_connection()
        reloaded = TerminalContextPreferenceStore(self.database)
        self.assertEqual(reloaded.get_preferences(), saved)

    def test_malformed_payload_resets_to_empty_selection(self):
        self.assertEqual(self.store.save_preferences({'field_ids': 'pid'}), {'field_ids': []})
        self.assertEqual(self.store.save_preferences(None), {'field_ids': []})


class TerminalContextPreferencesApiTests(unittest.TestCase):
    def test_api_delegates_get_and_save(self):
        class FakeStore:
            def get_preferences(self):
                return {'field_ids': ['status']}

            def save_preferences(self, payload):
                return {'field_ids': payload.get('field_ids', [])}

        api = WebTerminalContextPreferencesApi(FakeStore())
        self.assertEqual(api.get_preferences(), {'field_ids': ['status']})
        self.assertEqual(api.save_preferences({'field_ids': ['pid']}), {'field_ids': ['pid']})
