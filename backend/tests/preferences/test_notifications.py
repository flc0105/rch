"""Focused behavior tests for project module: preferences."""

import queue
import tempfile
import unittest
from pathlib import Path
from server.application.preferences.notification_history_store import NotificationHistoryStore
from server.application.web.notification_history_api import WebNotificationHistoryApi
from server.persistence.rch_database import RchDatabase
from server.web.event_bus import WebEventBus
from server.application.preferences.notification_preference_store import NotificationPreferenceStore
from server.application.preferences.notification_event_projector import NotificationEventProjector


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


class NotificationConnectionOfflineTests(unittest.TestCase):
    def test_offline_notification_includes_human_readable_termination_reason(self):
        projector = NotificationEventProjector(history_store=None, server=None)
        notification = projector._build_connection_offline({
            'client_id': 'client-X',
            'connection': {'client_id': 'client-X', 'hostname': 'Mac'},
            'termination_reason': 'connection_lost',
        })

        self.assertEqual(notification['message'], 'Mac went offline · Reason: Connection lost')
        self.assertEqual(notification['context']['termination_reason'], 'connection_lost')
