import queue
import tempfile
import unittest
from pathlib import Path

from server.application.preferences.notification_history_store import NotificationHistoryStore
from server.application.web.notification_history_api import WebNotificationHistoryApi
from server.persistence.rch_database import RchDatabase
from server.web.event_bus import WebEventBus


class NotificationClearTypeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = RchDatabase(str(Path(self.tmp.name) / 'rch.db'))
        self.bus = WebEventBus()
        self.listener = self.bus.subscribe(event_types={'notification_center_updated'})
        self.store = NotificationHistoryStore(self.db)
        self.api = WebNotificationHistoryApi(self.store, self.bus)
        for value, kind in [('s1', 'success'), ('w1', 'warning'), ('s2', 'success'), ('i1', 'info')]:
            self.store.add_notification({'id': value, 'title': value, 'type': kind})

    def tearDown(self):
        self.db.close_thread_connection()
        self.tmp.cleanup()

    def test_filtered_clear_only_removes_selected_type_and_broadcasts_ids(self):
        self.assertEqual(self.api.clear_history('success'), {'removed_count': 2})
        remaining = [row['id'] for row in self.store.get_history()['notifications']]
        self.assertCountEqual(remaining, ['w1', 'i1'])
        event = self.listener.get_nowait()
        self.assertEqual(event['data']['action'], 'pruned')
        self.assertCountEqual(event['data']['ids'], ['s1', 's2'])

    def test_empty_type_is_noop_but_all_keeps_existing_behavior(self):
        self.assertEqual(self.api.clear_history('error'), {'removed_count': 0})
        with self.assertRaises(queue.Empty):
            self.listener.get_nowait()
        self.assertEqual(self.api.clear_history(), {'removed_count': 4})
        self.assertEqual(self.listener.get_nowait()['data']['action'], 'cleared')
        self.assertEqual(self.store.get_history()['notifications'], [])

    def test_bad_type_rejected_without_deleting_any_notification(self):
        with self.assertRaises(ValueError):
            self.api.clear_history('everything')
        self.assertEqual(len(self.store.get_history()['notifications']), 4)


if __name__ == '__main__':
    unittest.main()
