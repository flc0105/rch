"""Authenticated loopback connections carrying length-prefixed process frames."""

from contextlib import contextmanager
import hmac
import secrets
import socket
import struct


_FRAME = struct.Struct('!cI')
MAX_FRAME_BYTES = 8192
_POLL_INTERVAL = 0.1


@contextmanager
def open_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(_POLL_INTERVAL)
        endpoint = {
            'port': listener.getsockname()[1],
            'token': secrets.token_hex(24),
            'ack': secrets.token_hex(24),
        }
        yield listener, endpoint


def read_frame(peer, checkpoint):
    def read_exact(size):
        buffer = bytearray()
        while len(buffer) < size:
            checkpoint()
            try:
                block = peer.recv(size - len(buffer))
            except TimeoutError:
                continue
            if not block:
                raise OSError('Local process channel closed before returning a complete frame')
            buffer.extend(block)
        return bytes(buffer)

    kind, size = _FRAME.unpack(read_exact(_FRAME.size))
    if size > MAX_FRAME_BYTES:
        raise OSError('Invalid frame size from local process')
    return kind, read_exact(size)


@contextmanager
def accept_peer(listener, endpoint, checkpoint, on_wait):
    while True:
        checkpoint()
        try:
            peer, _ = listener.accept()
            break
        except TimeoutError:
            on_wait()
    with peer:
        peer.settimeout(_POLL_INTERVAL)
        kind, token = read_frame(peer, checkpoint)
        if kind != b'T' or not hmac.compare_digest(token, endpoint['token'].encode('ascii')):
            raise OSError('Invalid authentication on local process channel')
        checkpoint()
        peer.sendall(endpoint['ack'].encode('ascii'))
        yield peer
