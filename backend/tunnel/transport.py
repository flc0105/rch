"""Small framed setup protocol and raw bidirectional byte relay for the optional tunnel."""
import json
import socket
import struct
import threading

_MAX_FRAME = 4096
_BUFFER = 65536


def _read_exact(sock, length):
    buf = bytearray()
    while len(buf) < length:
        chunk = sock.recv(length - len(buf))
        if not chunk:
            raise ConnectionError('Tunnel connection closed during handshake')
        buf.extend(chunk)
    return bytes(buf)


def send_frame(sock, data, lock=None):
    payload = json.dumps(data, separators=(',', ':')).encode('utf-8')
    if len(payload) > _MAX_FRAME:
        raise ValueError('Tunnel control frame too large')
    frame = struct.pack('!I', len(payload)) + payload
    if lock is None:
        sock.sendall(frame)
    else:
        with lock:
            sock.sendall(frame)


def recv_frame(sock):
    size = struct.unpack('!I', _read_exact(sock, 4))[0]
    if not 0 < size <= _MAX_FRAME:
        raise ValueError('Invalid tunnel frame length')
    data = json.loads(_read_exact(sock, size))
    if not isinstance(data, dict):
        raise ValueError('Invalid tunnel frame')
    return data


def listen(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(64)
        sock.settimeout(0.25)
        return sock
    except Exception:
        sock.close()
        raise


def close_socket(sock):
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


def bridge(left, right):
    """Copy bytes in both directions, propagating FIN after a half-close."""
    def copy(source, target):
        try:
            while True:
                chunk = source.recv(_BUFFER)
                if not chunk:
                    break
                target.sendall(chunk)
        except OSError:
            pass
        finally:
            try:
                target.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    t = threading.Thread(target=copy, args=(left, right), daemon=True, name='TunnelPipe')
    t.start()
    try:
        copy(right, left)
        t.join()
    finally:
        close_socket(left)
        close_socket(right)
