import queue
import tempfile
import unittest
from pathlib import Path

from server.application.preferences.notification_history_store import NotificationHistoryStore
from server.application.preferences.notification_preference_store import NotificationPreferenceStore
from server.persistence.rch_database import RchDatabase
from server.web.event_bus import WebEventBus


class NotificationReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = RchDatabase(str(Path(self.tmp.name) / 'rch.db'))
        self.store = NotificationHistoryStore(self.database)

    def tearDown(self):
        self.database.close_thread_connection()
        self.tmp.cleanup()

    def _add(self, notification_id, title):
        stored, created = self.store.add_notification({
            'id': notification_id,
            'title': title,
            'message': f'{title} body',
            'type': 'info',
        })
        self.assertTrue(created)
        return stored

    def test_replay_uses_insertion_order_after_notification_id(self):
        self._add('n1', 'one')
        self._add('n2', 'two')
        self._add('n3', 'three')

        replay = self.store.get_notifications_after('n1')

        self.assertTrue(replay['cursor_found'])
        self.assertEqual(['n2', 'n3'], [item['id'] for item in replay['notifications']])

    def test_missing_cursor_does_not_replay_old_history(self):
        self._add('n1', 'one')

        replay = self.store.get_notifications_after('missing')

        self.assertFalse(replay['cursor_found'])
        self.assertEqual([], replay['notifications'])


class NotificationEventBusFilterTests(unittest.TestCase):
    def test_filtered_subscriber_receives_only_requested_event_type(self):
        bus = WebEventBus()
        all_events = bus.subscribe()
        notifications = bus.subscribe(event_types={'notification_center_updated'})

        bus.publish('connection_online', {'client_id': 'one'})
        self.assertEqual('connection_online', all_events.get_nowait()['event'])
        with self.assertRaises(queue.Empty):
            notifications.get_nowait()

        bus.publish('notification_center_updated', {'action': 'added', 'notification': {'id': 'n1'}})
        self.assertEqual('notification_center_updated', notifications.get_nowait()['event'])


class NotificationPreferenceDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = RchDatabase(str(Path(self.tmp.name) / 'rch.db'))
        self.store = NotificationPreferenceStore(self.database)

    def tearDown(self):
        self.database.close_thread_connection()
        self.tmp.cleanup()

    def test_default_and_unknown_notification_keys_are_delivered(self):
        self.assertTrue(self.store.is_delivery_enabled('device_event'))
        self.assertTrue(self.store.is_delivery_enabled('future_notification_key'))
        self.assertTrue(self.store.is_delivery_enabled(''))

    def test_global_notification_switch_disables_desktop_delivery(self):
        self.store.save_preferences({'enabled': False})

        self.assertFalse(self.store.is_delivery_enabled('device_event'))
        self.assertFalse(self.store.is_delivery_enabled('future_notification_key'))

    def test_event_notification_switch_disables_only_that_delivery(self):
        self.store.save_preferences({
            'enabled': True,
            'events': {
                'device_event': False,
                'connection_online': True,
            },
        })

        self.assertFalse(self.store.is_delivery_enabled('device_event'))
        self.assertTrue(self.store.is_delivery_enabled('connection_online'))



if __name__ == '__main__':
    unittest.main()
