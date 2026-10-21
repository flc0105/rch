"""Log Viewer transport regression across Client monitor and existing tab-scoped SSE events."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from client.monitor.manager import DeviceMonitorManager
from core.protocol.message_types import MSG_TYPE_MONITOR_SNAPSHOT
from server.application.monitor.device_monitor_session_service import DeviceMonitorSessionService


class _MessageSink:
    def __init__(self):
        self.lock = threading.Lock()
        self.messages = []

    def send(self, message):
        with self.lock:
            self.messages.append(message)

    def snapshots(self):
        with self.lock:
            return [msg for msg in self.messages if msg.get('type') == MSG_TYPE_MONITOR_SNAPSHOT]


class _ServerStub:
    def __init__(self):
        self.connection = _MessageSink()

    def get_target_connection_by_client_id(self, client_id):
        if client_id != 'client-one':
            raise ValueError('Unknown client')
        return self.connection


class _EventBusStub:
    def __init__(self):
        self.events = []

    def publish(self, name, payload, *, target_tab_id):
        self.events.append((name, payload, target_tab_id))


class LogViewerTransportTests(unittest.TestCase):
    def test_client_tails_and_pushes_incremental_logs_without_command_polling(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'service.out'
            log.write_text('initial\n')
            sink = _MessageSink()
            manager = DeviceMonitorManager(sink)
            manager.open_session('log-live', ['log_file'], {'log_file': 0.25}, {'path': str(log)})
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not sink.snapshots():
                    time.sleep(0.03)
                snapshots = sink.snapshots()
                self.assertTrue(snapshots, 'Initial Client log snapshot was not sent')
                self.assertEqual(snapshots[0]['data']['content'], 'initial\n')
                with log.open('a') as output:
                    output.write('appended\n')
                while time.monotonic() < deadline and len(sink.snapshots()) < 2:
                    time.sleep(0.03)
                snapshots = sink.snapshots()
                self.assertGreaterEqual(len(snapshots), 2)
                self.assertEqual(snapshots[1]['data']['content'], 'appended\n')
                self.assertEqual(snapshots[1]['data']['path'], str(log))
            finally:
                manager.close_all_sessions(notify=False)

    def test_server_only_relays_existing_device_monitor_sse_to_owning_tab(self):
        server, event_bus = _ServerStub(), _EventBusStub()
        service = DeviceMonitorSessionService(server, event_bus)
        opened = service.create_session('client-one', 'tab-one', channels=['log_file'], options={'path': '/tmp/log.txt'})
        sid = opened['monitor_session_id']
        service.handle_client_snapshot(sid, 1, 'log_file', {'content': 'line\n', 'cursor': '1:1:1'}, time.time())
        self.assertEqual(len(event_bus.events), 1)
        name, payload, target_tab = event_bus.events[0]
        self.assertEqual(name, 'device_monitor_snapshot')
        self.assertEqual(target_tab, 'tab-one')
        self.assertEqual(payload['monitor_session_id'], sid)
        self.assertEqual(payload['data']['content'], 'line\n')
        service.close_session(sid, tab_id='tab-one')
        self.assertTrue(any(msg.get('type') for msg in server.connection.messages))


if __name__ == '__main__':
    unittest.main()
