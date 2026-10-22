"""Screen View must not take over an active viewer from another tab."""
import os
import sys
import threading
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core.protocol.message_types import MSG_TYPE_SCREEN_CLOSE, MSG_TYPE_SCREEN_OPEN
from server.application.screen.screen_view_session_service import ScreenViewSessionService


class FakeConnection:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(dict(payload))


class FakeServer:
    def __init__(self):
        self.connection = FakeConnection()

    def get_target_connection_by_client_id(self, _client_id):
        return self.connection


class ScreenViewSingleSessionGuardTests(unittest.TestCase):
    def test_active_session_rejects_duplicate_without_sending_close_or_open(self):
        server = FakeServer()
        service = ScreenViewSessionService(server)
        first = service.create_session('client-1')
        with self.assertRaisesRegex(ValueError, 'already open'):
            service.create_session('client-1')
        self.assertEqual([MSG_TYPE_SCREEN_OPEN], [item['type'] for item in server.connection.sent])
        self.assertEqual('opening', service.get_updates(first['screen_session_id'])['status'])

    def test_after_close_request_new_tab_may_open(self):
        server = FakeServer()
        service = ScreenViewSessionService(server)
        first = service.create_session('client-1')
        service.handle_client_opened(first['screen_session_id'])
        with self.assertRaisesRegex(ValueError, 'already open'):
            service.create_session('client-1')
        service.close_session(first['screen_session_id'])
        new = service.create_session('client-1')
        self.assertNotEqual(first['screen_session_id'], new['screen_session_id'])
        self.assertEqual('closing', service.get_updates(first['screen_session_id'])['status'])
        self.assertEqual('opening', service.get_updates(new['screen_session_id'])['status'])
        self.assertEqual(2, sum(item['type'] == MSG_TYPE_SCREEN_OPEN for item in server.connection.sent))
        self.assertEqual(1, sum(item['type'] == MSG_TYPE_SCREEN_CLOSE for item in server.connection.sent))

    def test_late_open_confirmation_cannot_revive_a_closing_session(self):
        service = ScreenViewSessionService(FakeServer())
        first = service.create_session('client-1')
        service.close_session(first['screen_session_id'])
        service.handle_client_opened(first['screen_session_id'])
        self.assertEqual('closing', service.get_updates(first['screen_session_id'])['status'])
        service.create_session('client-1')

    def test_different_clients_are_independent(self):
        service = ScreenViewSessionService(FakeServer())
        first = service.create_session('client-1')
        second = service.create_session('client-2')
        self.assertNotEqual(first['screen_session_id'], second['screen_session_id'])

    def test_simultaneous_open_does_not_race(self):
        service = ScreenViewSessionService(FakeServer())
        gate = threading.Barrier(3)
        results = []

        def open_one():
            gate.wait()
            try:
                service.create_session('client-1')
                results.append('opened')
            except ValueError:
                results.append('blocked')

        threads = [threading.Thread(target=open_one) for _ in range(2)]
        for thread in threads: thread.start()
        gate.wait()
        for thread in threads: thread.join(timeout=5)
        self.assertCountEqual(['opened', 'blocked'], results)


if __name__ == '__main__':
    unittest.main()
