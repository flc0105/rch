"""Listener sockets and network settings belong to each configured endpoint."""

from types import SimpleNamespace

import pytest

from server.runtime.server_listener import ServerListener


def test_listener_requires_config_and_does_not_borrow_server_socket():
    server = SimpleNamespace(address=('127.0.0.1', 10000), socket=object())
    with pytest.raises(TypeError):
        ServerListener(server)
    listener = ServerListener(server, config={'host': '127.0.0.1', 'port': 9999})
    assert listener.address == ('127.0.0.1', 9999)
    assert listener.socket is not server.socket
    listener.socket.close()
