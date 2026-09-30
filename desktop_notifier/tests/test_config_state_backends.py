import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rch_notifier.backends.macos import MacOSNotificationBackend
from rch_notifier.config import load_config
from rch_notifier.state import CursorState


class ConfigAndStateTests(unittest.TestCase):
    def test_config_loads_http_server_and_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps({
                'server_url': 'http://192.168.1.20:8085/',
                'token': 'secret',
                'backend': 'auto',
            }), encoding='utf-8')
            config = load_config(path)
            self.assertEqual('http://192.168.1.20:8085', config.server_url)
            self.assertEqual('http://192.168.1.20:8085/api/notifications/stream', config.stream_url)
            self.assertEqual('secret', config.token)

    def test_cursor_state_survives_reload_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            state = CursorState(path)
            state.update('n42')
            self.assertEqual('n42', CursorState(path).last_event_id)
            state.clear()
            self.assertEqual('', CursorState(path).last_event_id)


class MacBackendTests(unittest.TestCase):
    def test_auto_mode_falls_back_to_osascript_when_usernotifications_fails(self):
        backend = MacOSNotificationBackend(mode='auto', sound=True)
        with patch.object(backend, '_start_usernotifications', side_effect=RuntimeError('denied')), \
                patch.object(backend, '_ensure_osascript') as ensure:
            backend.start()
        ensure.assert_called_once_with()
        self.assertEqual('osascript', backend.active_mode)

    def test_osascript_delivery_uses_argv_not_shell_interpolation(self):
        backend = MacOSNotificationBackend(mode='osascript', sound=False)
        backend.active_mode = 'osascript'
        completed = Mock(returncode=0, stderr='', stdout='')
        with patch('rch_notifier.backends.macos.subprocess.run', return_value=completed) as run:
            self.assertTrue(backend.notify({'title': 'A "quoted" title', 'message': 'body; $(echo no)'}))
        args = run.call_args.args[0]
        self.assertEqual('/usr/bin/osascript', args[0])
        self.assertEqual('A "quoted" title', args[-2])
        self.assertEqual('body; $(echo no)', args[-1])


if __name__ == '__main__':
    unittest.main()
