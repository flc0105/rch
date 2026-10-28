"""Log-only monitor sessions work without psutil, including on Pythonista."""

import builtins
import threading

from client.monitor.manager import DeviceMonitorManager


class CaptureConnection:
    def __init__(self):
        self.messages = []
        self.snapshot = threading.Event()
        self.error = threading.Event()

    def send(self, message):
        self.messages.append(message)
        if message['type'] == 'monitor_snapshot':
            self.snapshot.set()
        if message['type'] == 'monitor_error':
            self.error.set()


def test_log_only_monitor_does_not_import_psutil(monkeypatch, tmp_path):
    log = tmp_path / 'client.log'
    log.write_text('Pythonista log\n', encoding='utf-8')
    conn = CaptureConnection()
    manager = DeviceMonitorManager(conn)
    original_import = builtins.__import__
    attempted = []

    def import_without_psutil(name, *args, **kwargs):
        if name == 'psutil' and threading.current_thread().name.startswith('device-monitor-'):
            attempted.append(name)
            raise ImportError('psutil not installed on iOS')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_without_psutil)
    manager.open_session('log-only', channels=['log_file'], options={'path': str(log)})
    try:
        assert conn.snapshot.wait(2), conn.messages
        assert not conn.error.is_set(), conn.messages
        assert attempted == []
        snapshot = next(m for m in conn.messages if m['type'] == 'monitor_snapshot')
        assert snapshot['channel'] == 'log_file'
        assert 'Pythonista log' in snapshot['data']['content']
    finally:
        manager.close_all_sessions(notify=False)
        worker = next(iter(manager._sessions.values()), {}).get('worker')
        if worker:
            worker.join(2)


def test_switch_from_log_to_metrics_imports_psutil(monkeypatch, tmp_path):
    log = tmp_path / 'client.log'
    log.write_text('ok\n', encoding='utf-8')
    conn = CaptureConnection()
    manager = DeviceMonitorManager(conn)
    original_import = builtins.__import__
    attempted = threading.Event()

    def import_without_psutil(name, *args, **kwargs):
        if name == 'psutil' and threading.current_thread().name.startswith('device-monitor-'):
            attempted.set()
            raise ImportError('psutil not installed')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_without_psutil)
    manager.open_session('dynamic-channel', channels=['log_file'], options={'path': str(log)})
    try:
        assert conn.snapshot.wait(2), conn.messages
        manager.update_session('dynamic-channel', channels=['system'])
        assert conn.error.wait(2), conn.messages
        assert attempted.is_set()
        assert any('psutil not installed' in m.get('message', '') for m in conn.messages)
    finally:
        manager.close_all_sessions(notify=False)
        worker = next(iter(manager._sessions.values()), {}).get('worker')
        if worker:
            worker.join(2)
