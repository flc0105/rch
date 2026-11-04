"""Protocol registration and unchanged TCP/TLS build/handshake behavior."""
import socket
import ssl
from types import SimpleNamespace

import pytest

from client.connection.transport_connectors import get_connector
from core.protocol.rchsocket import RCHSocket
from server.runtime.listener_manager import ListenerManager
from server.runtime.listener_protocols import get_listener_protocol, list_listener_protocols


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class _Server:
    def __init__(self):
        self.address = ('127.0.0.1', _free_port())
        self.socket = RCHSocket()
        self.connections = SimpleNamespace(all=lambda: [])


class _ConnectingSocket:
    def __init__(self):
        self.socket = None

    def connect(self, address):
        self.socket = socket.create_connection(address, timeout=3)
        return True

    def close(self):
        if self.socket:
            self.socket.close()


def test_registered_protocols_expose_build_rules_without_manager_switches():
    definitions = {entry['id']: entry for entry in list_listener_protocols()}
    assert definitions['tcp']['supported_builders'] is None
    assert definitions['tls_tcp']['supported_builders'] == ['bundle']
    assert definitions['tls_tcp']['build_label'] == 'TLS/TCP (pinned certificate)'
    with pytest.raises(ValueError, match='Unsupported listener protocol'):
        get_listener_protocol('not_registered')
    with pytest.raises(ValueError, match='Bundle'):
        get_listener_protocol('tls_tcp').validate_build('go', '0' * 64)
    with pytest.raises(ValueError, match='pinned'):
        get_listener_protocol('tls_tcp').validate_build('bundle', 'bad')


def test_factory_provides_build_settings_and_pinned_tls_connection(tmp_path):
    server = _Server()
    manager = ListenerManager(server, str(tmp_path / 'listeners.json'))
    manager.cert_dir = str(tmp_path / 'tls')
    manager.start_all()
    connection = _ConnectingSocket()
    try:
        tcp_settings = manager.build_settings('tcp-default', server.address[1], 'go')
        assert tcp_settings == {'listener_protocol': 'tcp', 'tls_fingerprint': ''}

        secure_port = _free_port()
        tls = manager.create({'name': 'Secure', 'protocol': 'tls_tcp',
                              'host': '127.0.0.1', 'port': secure_port})
        settings = manager.build_settings(tls['id'], secure_port, 'bundle')
        assert settings['listener_protocol'] == 'tls_tcp'
        assert settings['tls_fingerprint'] == manager.certificate_fingerprint(tls['id'])
        assert len(settings['tls_fingerprint']) == 64
        assert manager.list()[1]['supported_builders'] == ['bundle']
        with pytest.raises(ValueError, match='Bundle only'):
            manager.build_settings(tls['id'], secure_port, 'go')
        with pytest.raises(ValueError, match='does not match'):
            manager.build_settings(tls['id'], secure_port + 1, 'bundle')

        connector = get_connector('tls_tcp')
        config = {'server_tls_fingerprint': settings['tls_fingerprint']}
        connector.validate(config)
        assert connector.connect(connection, ('127.0.0.1', secure_port), config)
        assert isinstance(connection.socket, ssl.SSLSocket)
        connection.close()

        connection = _ConnectingSocket()
        with pytest.raises(ssl.SSLError, match='fingerprint mismatch'):
            connector.connect(connection, ('127.0.0.1', secure_port),
                              {'server_tls_fingerprint': '0' * 64})
    finally:
        connection.close()
        manager.stop_all()


def test_tcp_connector_uses_unchanged_plain_socket(tmp_path):
    with socket.socket() as listening:
        listening.bind(('127.0.0.1', 0))
        listening.listen(1)
        addr = listening.getsockname()
        outgoing = _ConnectingSocket()
        try:
            connector = get_connector('tcp')
            connector.validate({})
            assert connector.connect(outgoing, addr, {})
            with listening.accept()[0] as incoming:
                outgoing.socket.sendall(b'plaintext')
                assert incoming.recv(9) == b'plaintext'
            assert not isinstance(outgoing.socket, ssl.SSLSocket)
        finally:
            outgoing.close()
