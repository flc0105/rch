import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core.protocol.message_types import MSG_TYPE_SCREEN_INPUT, MSG_TYPE_SCREEN_OPEN
from core.protocol.screen import SCREEN_DEFAULT_CONTROL_ENABLED, SCREEN_DEFAULT_FPS
from server.application.screen.screen_view_session_service import ScreenViewSessionService


class FakeConnection:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(dict(payload or {}))


class FakeServer:
    def __init__(self):
        self.connection = FakeConnection()

    def get_target_connection_by_client_id(self, _client_id):
        return self.connection


class ScreenViewDefaultsRound3Tests(unittest.TestCase):
    def test_protocol_defaults_are_15_fps_and_control_on(self):
        self.assertEqual(15, SCREEN_DEFAULT_FPS)
        self.assertTrue(SCREEN_DEFAULT_CONTROL_ENABLED)

    def test_server_session_starts_with_default_fps_and_prepares_control(self):
        server = FakeServer()
        service = ScreenViewSessionService(server)

        result = service.create_session('client-1')
        self.assertEqual(15, result['fps'])
        self.assertTrue(result['control_enabled'])

        open_message = server.connection.sent[0]
        self.assertEqual(MSG_TYPE_SCREEN_OPEN, open_message['type'])
        self.assertEqual(15, open_message['fps'])

        service.handle_client_opened(
            result['screen_session_id'],
            fps=15,
            quality=60,
            frame_strategy='full_jpeg',
        )
        prepare_messages = [
            item for item in server.connection.sent
            if item.get('type') == MSG_TYPE_SCREEN_INPUT
            and (item.get('event') or {}).get('action') == 'prepare'
        ]
        self.assertEqual(1, len(prepare_messages))

        state = service.get_updates(result['screen_session_id'])
        self.assertEqual(15, state['fps'])
        self.assertTrue(state['control_enabled'])

    def test_frontend_defaults_match_server_defaults(self):
        source = Path(BACKEND_DIR).parent / 'frontend' / 'src' / 'components' / 'ScreenViewDialog.vue'
        text = source.read_text(encoding='utf-8')
        self.assertIn('controlEnabled: true,', text)
        self.assertIn('fps: 15,', text)
        self.assertIn('this.controlEnabled = true', text)
        self.assertIn("Object.prototype.hasOwnProperty.call(payload, 'control_enabled')", text)


if __name__ == '__main__':
    unittest.main()
