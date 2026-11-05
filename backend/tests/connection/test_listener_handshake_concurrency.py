import threading
import time
import ssl
from types import SimpleNamespace

from server.runtime.server_listener import ServerListener


class _RawSocket:
    def __init__(self, name):
        self.name = name
        self.closed = False
        self.closed_event = threading.Event()

    def settimeout(self, _value):
        pass

    def close(self):
        self.closed = True
        self.closed_event.set()


class _AcceptSocket:
    def __init__(self, accepted):
        self.accepted = list(accepted)

    def accept(self):
        return self.accepted.pop(0)


class _SlowFirstHandshake:
    def __init__(self):
        self.first_started = threading.Event()
        self.release_first = threading.Event()

    def wrap_socket(self, raw_sock, server_side):
        assert server_side is True
        if raw_sock.name == 'slow':
            self.first_started.set()
            assert self.release_first.wait(2)
        return raw_sock


def test_slow_tls_handshake_does_not_block_accepting_next_client():
    slow_socket = _RawSocket('slow')
    fast_socket = _RawSocket('fast')
    accept_socket = _AcceptSocket([
        (slow_socket, ('127.0.0.1', 1001)),
        (fast_socket, ('127.0.0.1', 1002)),
    ])
    server = SimpleNamespace(address=('127.0.0.1', 9999), socket=accept_socket)
    tls = _SlowFirstHandshake()
    listener = ServerListener(server, config={'host': '127.0.0.1', 'port': 9999}, ssl_context=tls)
    listener.socket = accept_socket
    processed = []
    fast_processed = threading.Event()

    def accept_session(raw_sock, addr, **_kwargs):
        processed.append(addr)
        if raw_sock.name == 'fast':
            fast_processed.set()

    listener.accept_session = accept_session

    listener._accept_connection()
    assert tls.first_started.wait(1)

    started = time.monotonic()
    listener._accept_connection()
    accept_elapsed = time.monotonic() - started

    try:
        assert accept_elapsed < 0.2
        assert fast_processed.wait(1)
        assert ('127.0.0.1', 1002) in processed
        assert ('127.0.0.1', 1001) not in processed
    finally:
        tls.release_first.set()
        deadline = time.monotonic() + 1
        while len(processed) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)

    assert ('127.0.0.1', 1001) in processed


def test_tls_handshake_failure_releases_bounded_slot():
    raw_socket = _RawSocket('bad-tls')
    accept_socket = _AcceptSocket([(raw_socket, ('127.0.0.1', 1003))])
    server = SimpleNamespace(address=('127.0.0.1', 9999), socket=accept_socket)

    class _FailingTLS:
        def wrap_socket(self, sock, server_side):
            raise ssl.SSLError('bad handshake')

    listener = ServerListener(server, config={'host': '127.0.0.1', 'port': 9999}, ssl_context=_FailingTLS())
    listener.socket = accept_socket
    listener._accept_connection()

    assert raw_socket.closed_event.wait(1)
    acquired = 0
    deadline = time.monotonic() + 1
    while acquired < listener.MAX_CONCURRENT_HANDSHAKES and time.monotonic() < deadline:
        if listener._handshake_slots.acquire(blocking=False):
            acquired += 1
        else:
            time.sleep(0.005)
    assert acquired == listener.MAX_CONCURRENT_HANDSHAKES
    for _ in range(acquired):
        listener._handshake_slots.release()
    assert raw_socket.closed


def test_listener_rejects_handshake_when_bounded_capacity_is_full():
    raw_socket = _RawSocket('overflow')
    accept_socket = _AcceptSocket([(raw_socket, ('127.0.0.1', 1004))])
    server = SimpleNamespace(address=('127.0.0.1', 9999), socket=accept_socket)
    listener = ServerListener(server, config={'host': '127.0.0.1', 'port': 9999})
    listener.socket = accept_socket
    acquired = [listener._handshake_slots.acquire(blocking=False)
                for _ in range(listener.MAX_CONCURRENT_HANDSHAKES)]
    assert all(acquired)
    try:
        listener._accept_connection()
        assert raw_socket.closed
    finally:
        for _ in acquired:
            listener._handshake_slots.release()
