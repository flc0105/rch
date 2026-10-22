"""Toolbox shortcut preferences store references only and preserve toolbar pins."""
import unittest

from server.application.preferences.toolbar_preference_store import ToolbarPreferenceStore


class ToolboxShortcutPreferencesTests(unittest.TestCase):
    def test_normalize_and_dedupe(self):
        store = object.__new__(ToolbarPreferenceStore)
        payload = store._normalize({
            'quick_actions_pinned': [{'platform': 'common', 'alias': 'ping'}],
            'toolbox_shortcuts': [
                {'kind': 'script', 'script_name': 'ops/check', 'icon': 'rocket', 'source': 'secret'},
                {'kind': 'script', 'script_name': 'ops/check', 'icon': 'zap'},
                {'kind': 'quick_action', 'platform': 'LINUX', 'alias': 'start', 'icon': 'terminal', 'command': 'private'},
                {'kind': 'background_job', 'job_name': 'monitor', 'icon': 'terminal'},
                {'kind': 'script', 'script_name': 'bad', 'icon': '<svg>'},
            ],
        })
        self.assertEqual(payload['toolbox_shortcuts'], [
            {'kind': 'script', 'script_name': 'ops/check', 'icon': 'rocket'},
            {'kind': 'quick_action', 'platform': 'linux', 'alias': 'start', 'icon': 'terminal'},
        ])
        self.assertEqual(payload['quick_actions_pinned'], [{'platform': 'common', 'alias': 'ping'}])

    def test_label_and_expanded_icons_are_validated(self):
        store = object.__new__(ToolbarPreferenceStore)
        payload = store._normalize({'toolbox_shortcuts': [
            {'kind': 'script', 'script_name': 'ops/a', 'icon': 'heart', 'label': ' My Favorite '},
            {'kind': 'quick_action', 'platform': 'WIN', 'alias': 'alias_long', 'icon': 'git-branch', 'label': 'Run Task'},
        ]})
        self.assertEqual(payload['toolbox_shortcuts'], [
            {'kind': 'script', 'script_name': 'ops/a', 'icon': 'heart', 'label': 'My Favorite'},
            {'kind': 'quick_action', 'platform': 'win', 'alias': 'alias_long', 'icon': 'git-branch', 'label': 'Run Task'},
        ])

    def test_save_and_reload(self):
        class MemorySettings:
            def __init__(self):
                self.saved = {}
            def read(self):
                return self.saved
            def write(self, payload):
                self.saved = payload
        store = object.__new__(ToolbarPreferenceStore)
        store.settings = MemorySettings()
        saved = store.save_preferences({'toolbox_shortcuts': [
            {'kind': 'script', 'script_name': 'ops/backup', 'icon': 'file-code'},
        ]})
        self.assertEqual(store.get_preferences()['toolbox_shortcuts'], saved['toolbox_shortcuts'])

    def test_invalid_shape(self):
        store = object.__new__(ToolbarPreferenceStore)
        self.assertEqual(store._normalize({'toolbox_shortcuts': 'not-list'})['toolbox_shortcuts'], [])
        self.assertEqual(store._normalize({'toolbox_shortcuts': [{'kind': 'script', 'icon': 'zap'}]})['toolbox_shortcuts'], [])


if __name__ == '__main__':
    unittest.main()
