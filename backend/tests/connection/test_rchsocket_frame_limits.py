import json
import socket
import struct
from types import SimpleNamespace

import pytest

from core.protocol.rchsocket import ProtocolFrameError, RCHSocket
from server.connection.connection_manager import ConnectionManager
from server.runtime.session_acceptor import SessionAcceptor


def _receiver(sock):
    receiver = RCHSocket()
    receiver.socket.close()
    receiver.socket = sock
    return receiver


@pytest.mark.parametrize('length', [-1, 0, RCHSocket.MAX_FRAME_BYTES + 1])
def test_recv_rejects_invalid_or_oversized_frame_length_before_body_read(length):
    left, right = socket.socketpair()
    receiver = _receiver(left)
    try:
        right.sendall(struct.pack(RCHSocket.HEADER_FORMAT, length))
        with pytest.raises(ValueError, match='Invalid message frame size'):
            receiver.recv()
    finally:
        receiver.close()
        right.close()


def test_recv_rejects_non_object_json_payload():
    left, right = socket.socketpair()
    receiver = _receiver(left)
    payload = json.dumps(['not', 'an', 'RCH message']).encode()
    try:
        right.sendall(struct.pack(RCHSocket.HEADER_FORMAT, len(payload)) + payload)
        with pytest.raises(ValueError, match='JSON object'):
            receiver.recv()
    finally:
        receiver.close()
        right.close()


@pytest.mark.parametrize('payload', [b'\xff', b'{invalid-json'])
def test_recv_rejects_invalid_utf8_or_json(payload):
    left, right = socket.socketpair()
    receiver = _receiver(left)
    try:
        right.sendall(struct.pack(RCHSocket.HEADER_FORMAT, len(payload)) + payload)
        with pytest.raises(ProtocolFrameError, match='Invalid RCH JSON frame'):
            receiver.recv()
    finally:
        receiver.close()
        right.close()


def test_send_rejects_frame_larger_than_shared_limit_before_writing():
    class _NoWriteSocket:
        def __init__(self):
            self.writes = []

        def sendall(self, data):
            self.writes.append(data)

    sender = RCHSocket()
    sender.socket.close()
    sender.socket = _NoWriteSocket()
    sender.MAX_FRAME_BYTES = 4

    with pytest.raises(ProtocolFrameError, match='maximum 4'):
        sender._send_packet(b'12345')
    assert sender.socket.writes == []


def test_send_rejects_non_object_payload():
    sender = RCHSocket()
    try:
        with pytest.raises(ProtocolFrameError, match='JSON object'):
            sender.send(['not', 'an', 'RCH message'])
    finally:
        sender.close()


def test_connection_handler_closes_session_after_invalid_protocol_frame():
    manager = ConnectionManager()
    closed = []

    class Session:
        def __init__(self):
            self.session_info = SimpleNamespace(client_id='client-frame')
            self.context = SimpleNamespace(transport_failure=None)
            self.address = '127.0.0.1:1234'
            self.runtime = SimpleNamespace(message_queue=SimpleNamespace(put=lambda *args: None))

        def recv_message(self):
            raise ProtocolFrameError('Invalid message frame size: -1 bytes')

        def close(self):
            closed.append(True)

    session = Session()
    manager.add(session)
    server = SimpleNamespace(
        connections=manager,
        web_service=SimpleNamespace(
            connection_api=SimpleNamespace(
                handle_connection_closed=lambda current: closed.append(current.context.transport_failure['reason'])
            )
        ),
    )
    acceptor = SessionAcceptor(server)

    acceptor.connection_handler(session)

    assert closed == [True, 'protocol_error']
    assert len(manager) == 0
