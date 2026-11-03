"""Session-end reporting must be recorded before a Client closes the transport."""

import socket
import threading
from types import SimpleNamespace

import pytest

from client.bootstrap.receiver_worker import ClientReceiverWorker
from client.commands.common.mixins.session_ops import CommandSessionMixin
from client.connection.server_connection import ServerConnection
from client.runtime import client_util
from core.protocol.message_types import MSG_TYPE_SESSION_END, MSG_TYPE_SESSION_END_ACK
from server.connection.client_session import ClientSession
from server.connection.transport.client_transport import ClientTransport


@pytest.mark.parametrize('reason,command', [
    ('server_requested_disconnect', 'kill_instance'),
    ('client_restart', 'relaunch_instance'),
    ('client_update', 'update'),
    ('client_paused', 'pause_connection'),
])
def test_real_socket_session_end_is_recorded_before_ack_and_shutdown(reason, command):
    """Exercise the actual Client receive worker, Server dispatcher, and TCP framing."""
    client_sock, server_sock = socket.socketpair()
    client = ServerConnection()
    client.socket.close()
    client.socket = client_sock
    client.mark_connected()
    server = ClientSession(ClientTransport(server_sock))
    receiver = ClientReceiverWorker()
    server_thread = threading.Thread(target=server.recv_message, daemon=True)
    try:
        receiver.start(client)
        server_thread.start()
        assert client.report_session_end(reason, command=command) is True
        server_thread.join(timeout=2)
        assert not server_thread.is_alive()
        report = server.context.client_session_end
        assert report['reason'] == reason
        assert report['detail']['command'] == command
    finally:
        receiver.stop()
        for sock in (client_sock, server_sock):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        receiver.join(timeout=2)


def test_timeout_waits_only_bounded_time_when_server_does_not_ack(monkeypatch):
    client = ServerConnection()
    try:
        messages = []
        client.send = messages.append
        client.mark_connected()
        monkeypatch.setattr(client, 'SESSION_END_ACK_TIMEOUT_SECONDS', 0.02)
        assert client.report_session_end('client_restart', command='relaunch_instance') is False
        assert len(messages) == 1
        assert messages[0]['type'] == MSG_TYPE_SESSION_END
        assert messages[0]['reason'] == 'client_restart'
        assert len(messages[0]['end_id']) == 32
    finally:
        client.close()


def test_wrong_ack_id_cannot_complete_shutdown_wait(monkeypatch):
    client = ServerConnection()
    try:
        client.mark_connected()
        monkeypatch.setattr(client, 'SESSION_END_ACK_TIMEOUT_SECONDS', 0.02)
        def fake_send(message):
            assert message['type'] == MSG_TYPE_SESSION_END
            client.handle_received_message({'type': MSG_TYPE_SESSION_END_ACK, 'end_id': 'not-the-request'})
        client.send = fake_send
        assert client.report_session_end('client_restart') is False
    finally:
        client.close()


def test_socket_send_failure_is_reported_not_hidden():
    client = ServerConnection()
    try:
        client.mark_connected()
        def send_fails(_):
            raise OSError('broken pipe')
        client.send = send_fails
        assert client.report_session_end('client_restart') is False
    finally:
        client.close()


def test_kill_reports_canonical_reason_before_closing():
    actions = []
    connection = SimpleNamespace(
        report_session_end=lambda reason, **kw: actions.append(('report', reason, kw)) or True,
        process_recovery_watchdog_manager=SimpleNamespace(stop=lambda: actions.append(('watchdog',))),
        close=lambda: actions.append(('close',)),
    )
    with pytest.raises(SystemExit) as exc:
        CommandSessionMixin.kill_instance(SimpleNamespace(socket=connection))
    assert exc.value.code == 0
    assert actions == [
        ('report', 'server_requested_disconnect', {'command': 'kill_instance'}),
        ('watchdog',),
        ('close',),
    ]


def test_relaunch_reports_restart_before_exit(monkeypatch):
    actions = []
    connection = SimpleNamespace(
        report_session_end=lambda reason, **kw: actions.append(('report', reason, kw)) or True,
        process_recovery_watchdog_manager=SimpleNamespace(stop=lambda: actions.append(('watchdog',))),
        close=lambda: actions.append(('close',)),
    )
    monkeypatch.setattr(client_util, 'spawn_new_instance', lambda: actions.append(('spawn',)))
    def fake_exit(code):
        actions.append(('exit', code))
        raise SystemExit(code)
    monkeypatch.setattr(client_util.os, '_exit', fake_exit)
    with pytest.raises(SystemExit) as exc:
        client_util.reset(connection)
    assert exc.value.code == 0
    assert actions == [
        ('spawn',),
        ('report', 'client_restart', {'command': 'relaunch_instance'}),
        ('watchdog',),
        ('close',),
        ('exit', 0),
    ]
