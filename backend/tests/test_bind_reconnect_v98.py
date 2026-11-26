"""Regression for a manually disconnected Bind Client and protocol mismatch diagnostics."""
import socket
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.runtime.bind_connector import BindConnector
from test_bind_tcp_phase_a import bind_server


def test_manual_bind_disconnect_leaves_a_full_reaccept_grace(monkeypatch):
    server = SimpleNamespace(connections=[])
    connector = BindConnector(server)
    fake = SimpleNamespace(
        session_info=SimpleNamespace(client_id='old-id'),
        bind_dial_endpoint=('127.0.0.1', 9443),
        note_server_disconnect=Mock(), close=Mock(),
        transport=SimpleNamespace(socket=SimpleNamespace(shutdown=Mock(side_effect=OSError()))),
    )
    connector._sessions[('127.0.0.1', 9443)] = fake
    server.connections.append(fake)
    connector.disconnect('old-id')
    remaining = connector._reconnect_until[('127.0.0.1', 9443)] - time.monotonic()
    assert 9.0 < remaining <= 10.0
    fake.note_server_disconnect.assert_called_once_with('disconnect')


def test_plain_bind_handshake_timeout_suggests_verifying_mtls(monkeypatch):
    connector = BindConnector(SimpleNamespace(connections=[]))
    sock = Mock()
    sock.getpeername.return_value = ('127.0.0.1', 9443)
    monkeypatch.setattr(socket, 'create_connection', lambda *_args, **_kwargs: sock)
    connector._acceptor.accept_session = Mock(side_effect=socket.timeout('timed out'))
    with pytest.raises(ConnectionError, match='Client may require mTLS/TCP'):
        connector._dial('127.0.0.1', 9443, '', 0, transport='tcp')
    sock.close.assert_called_once()


def test_mtls_bind_timeout_is_not_misreported_as_plain_tcp(monkeypatch):
    connector = BindConnector(SimpleNamespace(connections=[]))
    sock = Mock()
    monkeypatch.setattr(socket, 'create_connection', lambda *_args, **_kwargs: sock)
    identities = Mock()
    identities.wrap_outbound_socket.return_value = sock
    connector.server.listener_manager = SimpleNamespace(identities=identities)
    connector._acceptor.accept_session = Mock(side_effect=socket.timeout('timed out'))
    with pytest.raises(socket.timeout):
        connector._dial('127.0.0.1', 9443, '', 0, transport='mtls_tcp')


def test_first_manual_reconnect_retries_while_client_releases_old_session(monkeypatch):
    connector = BindConnector(SimpleNamespace(connections=[]))
    old = SimpleNamespace(
        session_info=SimpleNamespace(client_id='old-id'),
        bind_dial_endpoint=('127.0.0.1', 9443),
        note_server_disconnect=Mock(), close=Mock(),
        transport=SimpleNamespace(socket=SimpleNamespace(shutdown=Mock(side_effect=OSError()))),
    )
    connector._sessions[('127.0.0.1', 9443)] = old
    connector.server.connections.append(old)
    connector.disconnect('old-id')
    sock = Mock()
    sock.getpeername.return_value = ('127.0.0.1', 9443)
    monkeypatch.setattr(socket, 'create_connection', lambda *_args, **_kwargs: sock)
    replacement = SimpleNamespace(session_info=SimpleNamespace(client_id='new-id'))
    connector._acceptor.accept_session = Mock(side_effect=[OSError('old session pending'), replacement])
    connected, reused = connector.connect_with_status('127.0.0.1', 9443)
    assert connected is replacement and reused is False
    assert connector._acceptor.accept_session.call_count == 2


def test_real_bind_socket_reconnects_on_first_connect_after_release_delay(bind_server):
    from test_bind_tcp_phase_a import _connect_info, _wait_for
    from core.protocol.rchsocket import RCHSocket
    import threading
    
    _server, connector, port, _api = bind_server
    listener, accepted, _thread = _connect_info(port)
    replacement_peers = []
    try:
        first = connector.connect('127.0.0.1', port)
        connector.disconnect(first.session_info.client_id)

        def release_old_session():
            # A Client is still cleaning up while the operator clicks Connect.
            time.sleep(0.6)
            listener.release_session()
            accepted[0].close()
            incoming = listener.accept()
            sender = RCHSocket()
            sender.socket.close()
            sender.socket = incoming
            sender.send({'type': 'info', 'id': first.session_info.client_id})
            replacement_peers.append(sender)

        worker = threading.Thread(target=release_old_session, daemon=True)
        worker.start()
        connected, reused = connector.connect_with_status('127.0.0.1', port)
        assert not reused
        assert connected.session_info.client_id == first.session_info.client_id
        assert connected is not first
        assert _wait_for(lambda: bool(replacement_peers))
        connector.disconnect(connected.session_info.client_id)
        worker.join(timeout=2)
    finally:
        for peer in replacement_peers:
            peer.close()
        listener.close()


def test_plain_bind_closed_during_handshake_reports_possible_mismatch(monkeypatch):
    connector = BindConnector(SimpleNamespace(connections=[]))
    sock = Mock()
    monkeypatch.setattr(socket, 'create_connection', lambda *_args, **_kwargs: sock)
    connector._acceptor.accept_session = Mock(side_effect=OSError('Connection closed'))
    with pytest.raises(ConnectionError, match='may require mTLS/TCP'):
        connector._dial('127.0.0.1', 9443, '', 0, transport='tcp')
