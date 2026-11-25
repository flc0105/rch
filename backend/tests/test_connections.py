"""Connection recovery, mTLS handshake and session isolation."""

import hashlib
import socket
import ssl
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.connection.receiver_worker import ClientReceiverWorker
from client.connection.transport_connectors import MtlsConnector
from core.protocol.rchsocket import RCHSocket
from server.application.connection.connection_service import WebConnectionService
from server.application.connection.recent_device_store import RecentDeviceStore
from server.application.web.connection_api import WebConnectionApi
from server.connection.connection_manager import ConnectionManager
from server.persistence.rch_database import RchDatabase
from server.runtime.session_acceptor import SessionAcceptor


class _Session:
    def __init__(self, client_id, address):
        self.session_info = SimpleNamespace(client_id=client_id)
        self.context = SimpleNamespace(transport_failure=None)
        self.address = address
        self.runtime = SimpleNamespace(
            message_queue=SimpleNamespace(put=lambda *args: None), pending_results=SimpleNamespace(close=lambda: None),
        )


class _ConnectionApi:
    def __init__(self):
        self.closed = []

    def handle_connection_closed(self, session):
        self.closed.append(session)


def _acceptor(manager, api):
    server = SimpleNamespace(
        connections=manager,
        web_service=SimpleNamespace(connection_api=api),
    )
    return SessionAcceptor(server)


def test_old_session_close_cannot_cleanup_replacement_session():
    manager = ConnectionManager()
    api = _ConnectionApi()
    acceptor = _acceptor(manager, api)
    old_session = _Session('client-A', '127.0.0.1:1001')
    new_session = _Session('client-A', '127.0.0.1:1002')
    manager.add(old_session)
    manager.add(new_session)

    acceptor._handle_connection_closed(old_session)

    assert api.closed == []
    assert manager.get_by_client_id('client-A') is new_session


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


def test_mtls_connector_requires_context_and_wraps_before_rch(monkeypatch):
    from client.connection import transport_connectors as module
    socket_under_test = Mock()
    wrapped = Mock()
    context = Mock()
    context.wrap_socket.return_value = wrapped
    create = Mock(return_value=context)
    monkeypatch.setattr(module, 'create_context', create)
    connection = SimpleNamespace(socket=socket_under_test, connect=Mock(return_value=True))
    connector = MtlsConnector()
    assert connector.connect(connection, ('rch.example', 9999), {'identity_dir': '/identity'})
    assert connection.socket is wrapped
    create.assert_called_once_with({'identity_dir': '/identity'}, server_side=False)
    context.wrap_socket.assert_called_once_with(socket_under_test, server_hostname=None)


def test_mtls_connector_fails_closed_on_handshake_error(monkeypatch):
    from client.connection import transport_connectors as module
    context = Mock()
    context.wrap_socket.side_effect = ssl.SSLError('untrusted server')
    monkeypatch.setattr(module, 'create_context', lambda *_args, **_kwargs: context)
    raw = Mock()
    connection = SimpleNamespace(socket=raw, connect=Mock(return_value=True))
    with pytest.raises(ssl.SSLError, match='untrusted server'):
        MtlsConnector().connect(connection, ('rch.example', 9999), {})
    raw.close.assert_called_once()


def test_handshake_frame_rejects_oversized_length():
    import struct
    left, right = socket.socketpair()
    try:
        receiver = RCHSocket()
        receiver.socket.close()
        receiver.socket = left
        right.sendall(struct.pack(RCHSocket.HEADER_FORMAT, 9 * 1024 * 1024))
        with pytest.raises(ValueError, match='frame size'):
            receiver.recv(max_bytes=8 * 1024 * 1024)
    finally:
        left.close()
        right.close()


def test_replaced_connection_pending_results_are_session_scoped():
    from server.connection.connection_manager import ConnectionManager
    from server.runtime.session_acceptor import SessionAcceptor
    from server.connection.runtime.session_runtime import ClientSessionRuntime
    manager = ConnectionManager()
    def session():
        return SimpleNamespace(session_info=SimpleNamespace(client_id='same'), context=SimpleNamespace(),
                               runtime=ClientSessionRuntime(), address='test')
    old, new = session(), session()
    first = old.runtime.pending_results.register(1)
    second = new.runtime.pending_results.register(1)
    manager.add(old)
    manager.add(new)
    closed, replaced = [], []
    api = SimpleNamespace(handle_connection_closed=closed.append, handle_replaced_connection_closed=replaced.append)
    acceptor = SessionAcceptor(SimpleNamespace(connections=manager, web_service=SimpleNamespace(connection_api=api)))
    acceptor._handle_connection_closed(old)
    assert closed == [] and replaced == [old]
    assert first.get(timeout=.1) is None
    assert manager.get_by_client_id('same') is new
    assert new.runtime.pending_results.deliver(1, {'type':'result','id':1,'event_type':'completed','status':'success','message':'new'})
    assert second.get(timeout=.1)['message'] == 'new'


def test_reorder_preserves_other_device_slots_and_rejects_offline_machines(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = RecentDeviceStore(database)
    try:
        for machine_id, state in [('a', 'online'), ('offline', 'offline'), ('b', 'online'), ('stale', 'stale')]:
            store.upsert_from_connection({'machine_id': machine_id, 'connection_state': state})

        old = (datetime.now() - timedelta(minutes=2)).isoformat()
        sessions = [
            SimpleNamespace(session_info=SimpleNamespace(machine_id=key),
                            context=SimpleNamespace(disconnected_at='', last_seen_at=seen))
            for key, seen in [('a', ''), ('A', ''), ('b', ''), ('stale', old)]
        ]
        server = SimpleNamespace(connections=SimpleNamespace(all=lambda: sessions))
        api = WebConnectionApi(WebConnectionService(server, None, None, recent_device_store=store))
        api.reorder_online_devices([' B ', 'A'])
        store.upsert_from_connection({'machine_id': 'b', 'connection_state': 'online'})

        for invalid in (['a', 'offline'], ['b', 'stale']):
            with pytest.raises(ValueError, match='no longer online'):
                api.reorder_online_devices(invalid)
        with pytest.raises(ValueError, match='distinct machine IDs'):
            api.reorder_online_devices(['a', 'A'])

        assert {row['machine_id']: row['machine_order'] for row in store.list_recent_devices()} == {
            'b': 0, 'offline': 1, 'a': 2, 'stale': 3,
        }
    finally:
        database.close_thread_connection()
