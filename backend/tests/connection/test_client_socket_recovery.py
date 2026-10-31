"""Deterministic TCP blackhole and Client recovery regression tests."""

import queue
import socket
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from client.bootstrap.client_app import Client
from client.bootstrap.connection_lifecycle import ClientConnectionLifecycle
from client.bootstrap.receiver_worker import ClientReceiverWorker
from core.protocol.rchsocket import RCHSocket


class _NoMoreWait(BaseException):
    """Test-only exit from Client.wait's otherwise permanent loop."""


class _ReceiveConnection(RCHSocket):
    def __init__(self, sock):
        super().__init__()
        self.socket.close()
        self.socket = sock
        self.received = []

    def recv_message(self):
        self.received.append(self.recv())


def _open_tcp_pair():
    """A real loopback TCP session, whose server stays connected but can be silent."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    client = socket.create_connection(listener.getsockname(), timeout=2)
    server, _ = listener.accept()
    listener.close()
    client.settimeout(None)
    server.settimeout(None)
    return client, server


def _send(server, data):
    transport = RCHSocket()
    transport.socket.close()
    transport.socket = server
    transport.send(data)


def test_silent_established_tcp_triggers_client_recovery_without_fin_or_rst():
    client_sock, server_sock = _open_tcp_pair()
    connection = _ReceiveConnection(client_sock)
    worker = ClientReceiverWorker()
    worker.start(connection)
    probe = Client.__new__(Client)
    probe.receiver_worker = worker
    probe.server = Mock()
    probe.RECEIVE_IDLE_TIMEOUT_SECONDS = 0.1
    pending = queue.Queue()
    probe.server.recv_command.side_effect = lambda timeout: pending.get(timeout=timeout)
    observed = []

    def observe_recovery(error):
        observed.append(error)
        raise _NoMoreWait()

    probe._recover_from_connection_error = observe_recovery
    try:
        # A TCP connection is genuinely established; the peer does not send or close.
        assert connection.socket.getpeername() == server_sock.getsockname()
        with pytest.raises(_NoMoreWait):
            probe.wait()
        assert len(observed) == 1
        assert isinstance(observed[0], TimeoutError)
        assert 'inbound message timeout' in str(observed[0])
        assert worker._thread.is_alive()  # recv was really blocked, no FIN / RST
    finally:
        worker.stop()
        connection.shutdown()
        connection.close()
        assert worker.join(timeout=2)
        server_sock.close()


def test_real_heartbeat_resets_receive_idle_deadline():
    client_sock, server_sock = _open_tcp_pair()
    connection = _ReceiveConnection(client_sock)
    worker = ClientReceiverWorker()
    worker.start(connection)
    try:
        time.sleep(0.06)
        initial_idle = worker.receive_idle_seconds()
        assert initial_idle > 0.04
        _send(server_sock, {'type': 'heartbeat', 'id': 1})
        deadline = time.monotonic() + 2
        while not connection.received and time.monotonic() < deadline:
            time.sleep(0.005)
        assert connection.received == [{'type': 'heartbeat', 'id': 1}]
        assert worker.receive_idle_seconds() < initial_idle
    finally:
        worker.stop()
        connection.shutdown()
        connection.close()
        assert worker.join(timeout=2)
        server_sock.close()


def test_recovery_closes_old_socket_wakes_recv_and_clears_runtime():
    client_sock, server_sock = _open_tcp_pair()
    connection = _ReceiveConnection(client_sock)
    connection.runtime = Mock()
    connection.mark_disconnected = Mock()
    connection.reset_runtime_state = Mock()
    worker = ClientReceiverWorker()
    worker.start(connection)
    client = SimpleNamespace(server=connection, receiver_worker=worker)
    lifecycle = ClientConnectionLifecycle(client)
    next_connection = Mock()
    with patch.object(lifecycle, 'create_connection', return_value=next_connection):
        try:
            lifecycle.reset_connection()
            assert client.server is next_connection
            assert worker._thread is None
            connection.mark_disconnected.assert_called_once()
            connection.runtime.handle_connection_lost.assert_called_once()
            connection.reset_runtime_state.assert_called_once()
            assert worker.receive_idle_seconds() is None
        finally:
            server_sock.close()


def test_reconnection_retries_failed_handshake_instead_of_exiting():
    client = Client.__new__(Client)
    client.connection_lifecycle = Mock()
    client.RECONNECT_INTERVAL = 0.01
    client.connect = Mock(side_effect=[OSError('handshake interrupted'), None])
    with patch('client.bootstrap.client_app.time.sleep') as sleep:
        client._recover_from_connection_error(TimeoutError('idle'))
    assert client.connect.call_count == 2
    assert client.connection_lifecycle.reset_connection.call_count == 2
    sleep.assert_called_once_with(0.01)


def test_receiver_stale_stop_event_cannot_restart_old_socket_reader():
    client_sock, server_sock = _open_tcp_pair()
    connection = _ReceiveConnection(client_sock)
    worker = ClientReceiverWorker()
    worker.start(connection)
    old_event = worker._stop_event
    try:
        worker.stop()
        connection.shutdown()
        connection.close()
        assert worker.join(timeout=2)
        worker.reset_runtime()
        assert old_event is not worker._stop_event
        assert old_event.is_set()
    finally:
        server_sock.close()
