"""Multi-listener socket and certificate pinning regression tests."""
import hashlib
import socket
import ssl
from types import SimpleNamespace

import pytest

from core.protocol.rchsocket import RCHSocket
from server.runtime.listener_manager import ListenerManager


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class _Server:
    def __init__(self):
        self.address = ('127.0.0.1', _free_port())
        self.socket = RCHSocket()
        self.connections = SimpleNamespace(all=lambda: [])


def test_multiple_listener_lifecycle_and_persistence(tmp_path):
    server = _Server()
    path = tmp_path / 'listeners.json'
    manager = ListenerManager(server, str(path))
    manager.cert_dir = str(tmp_path / 'tls')
    manager.start_all()
    try:
        assert manager.list()[0]['status'] == 'listening'
        port = _free_port()
        created = manager.create({'name': 'LAN backup', 'protocol': 'tcp',
                                  'host': '127.0.0.1', 'port': port})
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            pass
        assert len(manager.list()) == 2
        with pytest.raises(ValueError, match='conflict'):
            manager.create({'name': 'conflicting', 'protocol': 'tcp',
                            'host': '0.0.0.0', 'port': port})
        manager.set_enabled(created['id'], False)
        assert manager.list()[1]['status'] == 'stopped'
        manager.set_enabled(created['id'], True)
        assert manager.list()[1]['status'] == 'listening'
        manager.remove(created['id'])
        assert len(manager.list()) == 1
        with pytest.raises(ValueError, match='Default'):
            manager.remove('tcp-default')
    finally:
        manager.stop_all()
    assert ListenerManager(server, str(path)).list()[0]['id'] == 'tcp-default'


def test_tls_listener_uses_persistent_pinned_certificate(tmp_path):
    server = _Server()
    manager = ListenerManager(server, str(tmp_path / 'listeners.json'))
    manager.cert_dir = str(tmp_path / 'tls')
    manager.start_all()
    try:
        port = _free_port()
        created = manager.create({'name': 'TLS', 'protocol': 'tls_tcp',
                                  'host': '127.0.0.1', 'port': port})
        expected = manager.certificate_fingerprint(created['id'])
        assert len(expected) == 64
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
            with context.wrap_socket(sock, server_hostname='localhost') as tls:
                assert hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest() == expected
        assert manager.certificate_fingerprint(created['id']) == expected
    finally:
        manager.stop_all()


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
