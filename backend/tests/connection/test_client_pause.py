"""Client-only Pause, authenticated IPC and watchdog resume regression tests."""

import os
import queue
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from client.bootstrap.client_app import Client
from client.bootstrap.connection_lifecycle import ClientConnectionLifecycle
from client.connection.server_connection import ServerConnection
from client.runtime.local_ipc import LocalIpcServer, send_local_command
from client.watchdog.remote_control_watchdog import RemoteControlWatchdogMonitor


def test_pause_is_a_normal_client_command_and_does_not_require_watchdog():
    from client.commands.common.mixins.session_ops import CommandSessionMixin

    fake_socket = Mock()
    command = CommandSessionMixin()
    command.socket = fake_socket
    assert command.pause_connection()[0] == 1
    fake_socket.request_pause.assert_called_once()
    conn = ServerConnection.__new__(ServerConnection)
    conn._pause_requested = False
    assert not conn.consume_pause_request()
    conn.request_pause()
    assert conn.consume_pause_request()
    assert not conn.consume_pause_request()


def test_pause_gate_blocks_until_ipc_resume_without_relaunch():
    fake = SimpleNamespace()
    fake.server = Mock()
    fake.receiver_worker = Mock()
    fake.receiver_worker.join.return_value = True
    fake.client_id = 'original-id'
    fake.watchdog_manager = None
    fake.process_recovery_watchdog_manager = None
    lifecycle = ClientConnectionLifecycle(fake)
    with patch.object(lifecycle, 'create_connection', return_value=Mock()):
        lifecycle.pause()
    assert lifecycle.is_paused
    waiting = threading.Event()
    done = threading.Event()

    def wait():
        waiting.set()
        lifecycle.wait_until_active()
        done.set()

    t = threading.Thread(target=wait)
    t.start()
    assert waiting.wait(1)
    assert not done.wait(0.1)
    # Existing same-process handshake identity is unchanged.
    lifecycle.resume()
    assert done.wait(1)
    t.join(timeout=1)
    assert not lifecycle.is_paused
    assert fake.client_id == 'original-id'
    lifecycle.resume()  # idempotent
    assert not lifecycle.is_paused


def test_authentic_local_ipc_resumes_exact_client_instance():
    ipc = LocalIpcServer()
    calls = []
    ipc.register('connection.resume', lambda: calls.append('resume'))
    ipc.start()
    try:
        assert send_local_command('connection.resume', ipc.address, ipc.authkey)['ok']
        assert calls == ['resume']
        with pytest.raises(RuntimeError, match='Unknown IPC action'):
            send_local_command('connection.nonexistent', ipc.address, ipc.authkey)
        assert calls == ['resume']
    finally:
        ipc.stop()
    if os.name != 'nt':
        assert not os.path.exists(ipc.address)


def test_subprocess_delivers_resume_using_watchdog_environment():
    ipc = LocalIpcServer()
    resumed = threading.Event()
    ipc.register('connection.resume', resumed.set)
    ipc.start()
    try:
        env = {**os.environ, **ipc.child_environment()}
        result = subprocess.run(
            [sys.executable, '-c',
             'from client.runtime.local_ipc import send_local_command; '
             'send_local_command("connection.resume")'],
            env=env, check=True, capture_output=True, text=True, timeout=8,
        )
        assert result.returncode == 0
        assert resumed.wait(1)
    finally:
        ipc.stop()


def test_pause_result_is_sent_before_socket_is_closed():
    client = Client.__new__(Client)
    client.server = Mock()
    client.receiver_worker = Mock()
    client.receiver_worker.receive_idle_seconds.return_value = None
    client.receiver_worker.pop_error.return_value = None
    client.server.recv_command.side_effect = [(99, 1, 'paused'), SystemExit()]
    client.server.consume_pause_request.return_value = True
    client.connection_lifecycle = Mock()
    client.connection_lifecycle.is_paused = False
    client.local_ipc = Mock()
    records = []
    client.connect = lambda: records.append('connect')
    client.server.send_result.side_effect = lambda *args: records.append('result')
    client.server.report_session_end.side_effect = lambda *args, **kw: records.append(('end', args, kw))
    client.connection_lifecycle.pause.side_effect = lambda: records.append('pause')
    client._wait_for_commands()
    assert records == ['result', ('end', ('client_paused',), {'command': 'pause_connection'}), 'pause', 'connect']


def test_paused_client_does_not_call_idle_recovery_or_read_messages():
    client = Client.__new__(Client)
    client.server = Mock()
    client.receiver_worker = Mock()
    class Gate:
        is_paused = True
        def wait_until_active(self):
            raise SystemExit()
    client.connection_lifecycle = Gate()
    with pytest.raises(SystemExit):
        client._wait_for_commands()
    client.server.recv_command.assert_not_called()
    client.receiver_worker.pop_error.assert_not_called()


def test_paused_client_stays_offline_past_receive_idle_timeout():
    client = Client.__new__(Client)
    client.server = Mock()
    client.receiver_worker = Mock()
    client.receiver_worker.pop_error.return_value = None
    client.receiver_worker.receive_idle_seconds.return_value = None
    client.server.recv_command.side_effect = SystemExit()
    client.RECEIVE_IDLE_TIMEOUT_SECONDS = 0.01
    lifecycle = ClientConnectionLifecycle(client)
    lifecycle._active.clear()
    client.connection_lifecycle = lifecycle
    client.connect = Mock()
    worker = threading.Thread(target=client._wait_for_commands, daemon=True)
    worker.start()
    time.sleep(0.08)
    assert worker.is_alive()
    client.connect.assert_not_called()
    client.server.recv_command.assert_not_called()
    lifecycle.resume()
    worker.join(timeout=2)
    assert not worker.is_alive()
    client.connect.assert_called_once()


def test_remote_watchdog_resume_delivers_ipc_not_process_relaunch(tmp_path):
    from client.watchdog import remote_control_watchdog as wd

    executor = Mock()
    log = str(tmp_path / 'remote.log')
    monitor = RemoteControlWatchdogMonitor(
        client_id='original-id', base_url='http://localhost', poll_interval=15,
        remote_control_watchdog_log_file_path=log, action_executor=executor,
    )
    with patch.object(wd, 'send_local_command') as send:
        monitor._execute_command('resume')
    send.assert_called_once_with('connection.resume')
    executor.restart_parent_and_exit.assert_not_called()
    executor.spawn_new_instance.assert_not_called()
    executor.kill_parent_and_exit.assert_not_called()


def test_unexpected_socket_failure_still_uses_reconnection_path():
    client = Client.__new__(Client)
    client.RECONNECT_INTERVAL = 0.01
    client.connection_lifecycle = Mock()
    client.connect = Mock()
    client._recover_from_connection_error(socket.error('network fail'))
    client.connection_lifecycle.reset_connection.assert_called_once()
    client.connect.assert_called_once()
