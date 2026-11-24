"""Bounded first-frame greeting for independent connections on an RCH port."""
import json
import socket
import struct

from core.protocol.rchsocket import RCHSocket

MAX_GREETING = 4096


def close_socket(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def read_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise ConnectionError('Data connection closed')
        result.extend(chunk)
    return bytes(result)


def send_greeting(sock, packet):
    payload = json.dumps(packet, separators=(',', ':')).encode('utf-8')
    if not 0 < len(payload) <= MAX_GREETING:
        raise ValueError('Invalid auxiliary greeting size')
    sock.sendall(struct.pack(RCHSocket.HEADER_FORMAT, len(payload)) + payload)


def receive_greeting(sock):
    sock.settimeout(5)
    try:
        length = struct.unpack(RCHSocket.HEADER_FORMAT, read_exact(sock, RCHSocket.HEADER_SIZE))[0]
        if not 0 < length <= MAX_GREETING:
            raise ValueError('Invalid auxiliary greeting size')
        packet = json.loads(read_exact(sock, length))
        if not isinstance(packet, dict):
            raise ValueError('Invalid auxiliary greeting')
        return packet
    finally:
        sock.settimeout(None)
