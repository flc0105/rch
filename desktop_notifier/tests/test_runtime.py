import threading
import time
import unittest

from rch_notifier.runtime import NotificationStreamRuntime
from rch_notifier.sse import SseEvent


class _Config:
    stream_url = 'http://server/api/notifications/stream'
    token = 'secret'
    reconnect_initial_seconds = 1.0
    reconnect_max_seconds = 30.0


class _State:
    def __init__(self):
        self.last_event_id = ''
        self.updated = []
        self.cleared = False

    def update(self, notification_id):
        self.last_event_id = notification_id
        self.updated.append(notification_id)

    def clear(self):
        self.last_event_id = ''
        self.cleared = True


class _Backend:
    def __init__(self):
        self.notifications = []

    def notify(self, notification):
        self.notifications.append(dict(notification))
        return True


class _OneEventClient:
    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.closed = 0

    def events(self, _cursor, *, on_open=None):
        if on_open:
            on_open()
        yield SseEvent(
            event='notification',
            event_id='n1',
            data='{"id":"n1","title":"Hello","message":"World"}',
        )
        self.stop_event.set()

    def close_active_response(self):
        self.closed += 1




class _CursorThenNotificationClient:
    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.closed = 0

    def events(self, _cursor, *, on_open=None):
        if on_open:
            on_open()
        yield SseEvent(
            event='cursor',
            event_id='n1',
            data='{"notification_id":"n1","reason":"disabled_by_preference"}',
        )
        yield SseEvent(
            event='notification',
            event_id='n2',
            data='{"id":"n2","title":"Visible","message":"Delivered"}',
        )
        self.stop_event.set()

    def close_active_response(self):
        self.closed += 1


class _CloseTrackingClient:
    def __init__(self):
        self.closed = 0

    def close_active_response(self):
        self.closed += 1


class RuntimeTests(unittest.TestCase):
    def test_notification_delivery_updates_cursor_and_status(self):
        state = _State()
        backend = _Backend()
        statuses = []
        runtime = NotificationStreamRuntime(
            config=_Config(),
            state=state,
            backend=backend,
            status_callback=lambda connected, retry: statuses.append((connected, retry)),
        )
        runtime.client = _OneEventClient(runtime.stop_event)

        self.assertEqual(0, runtime.run())
        self.assertEqual(['n1'], state.updated)
        self.assertEqual('Hello', backend.notifications[0]['title'])
        self.assertIn((True, None), statuses)


    def test_cursor_event_advances_state_without_desktop_notification(self):
        state = _State()
        backend = _Backend()
        runtime = NotificationStreamRuntime(config=_Config(), state=state, backend=backend)
        runtime.client = _CursorThenNotificationClient(runtime.stop_event)

        self.assertEqual(0, runtime.run())
        self.assertEqual(['n1', 'n2'], state.updated)
        self.assertEqual(1, len(backend.notifications))
        self.assertEqual('Visible', backend.notifications[0]['title'])

    def test_manual_reconnect_interrupts_active_stream(self):
        runtime = NotificationStreamRuntime(config=_Config(), state=_State(), backend=_Backend())
        client = _CloseTrackingClient()
        runtime.client = client

        runtime.reconnect()

        self.assertTrue(runtime.reconnect_event.is_set())
        self.assertEqual(1, client.closed)

    def test_stop_interrupts_active_stream(self):
        runtime = NotificationStreamRuntime(config=_Config(), state=_State(), backend=_Backend())
        client = _CloseTrackingClient()
        runtime.client = client

        runtime.stop()

        self.assertTrue(runtime.stop_event.is_set())
        self.assertEqual(1, client.closed)

    def test_manual_reconnect_wakes_retry_countdown_immediately(self):
        statuses = []
        runtime = NotificationStreamRuntime(
            config=_Config(),
            state=_State(),
            backend=_Backend(),
            status_callback=lambda connected, retry: statuses.append((connected, retry)),
        )
        client = _CloseTrackingClient()
        runtime.client = client
        result = {}

        thread = threading.Thread(target=lambda: result.setdefault('value', runtime._wait_for_retry(10)))
        thread.start()
        time.sleep(0.02)
        runtime.reconnect()
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertTrue(result['value'])
        self.assertTrue(any(not connected and retry for connected, retry in statuses))


if __name__ == '__main__':
    unittest.main()
