"""File data framing shared by both endpoints and connection directions."""
import hashlib
import json
import os
import struct

from core.protocol.auxiliary import read_exact
from core.transfer_settings import DEFAULT_HTTP_TRANSFER_BUFFER_SIZE

DATA_GREETING = 'transfer_data'
IO_TIMEOUT = 120
MAX_CONTROL_SIZE = 1024 * 1024


def send_control(sock, packet):
    body = json.dumps(packet, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if not 0 < len(body) <= MAX_CONTROL_SIZE:
        raise ValueError('Invalid file control frame size')
    sock.sendall(struct.pack('!I', len(body)) + body)


def receive_control(sock):
    size = struct.unpack('!I', read_exact(sock, 4))[0]
    if not 0 < size <= MAX_CONTROL_SIZE:
        raise ValueError('Invalid file control frame size')
    packet = json.loads(read_exact(sock, size))
    if not isinstance(packet, dict):
        raise ValueError('Invalid file control frame')
    return packet


def require_ok(sock):
    result = receive_control(sock)
    if result.get('ok') is not True:
        raise RuntimeError(str(result.get('error') or 'File transfer rejected'))
    return result


def send_file(sock, path, *, metadata=None, checkpoint=lambda: None, progress=None,
              buffer_size=DEFAULT_HTTP_TRANSFER_BUFFER_SIZE):
    with open(path, 'rb') as source:
        size = os.fstat(source.fileno()).st_size
        send_control(sock, {'size': size, **(metadata or {})})
        digest = hashlib.sha256()
        sent = 0
        while sent < size:
            checkpoint()
            chunk = source.read(min(buffer_size, size - sent))
            if not chunk:
                raise IOError('Source file changed during transfer')
            sock.sendall(chunk)
            digest.update(chunk)
            sent += len(chunk)
            if progress:
                progress(sent, size)
        checkpoint()
        if source.read(1):
            raise IOError('Source file changed during transfer')
        send_control(sock, {'sha256': digest.hexdigest()})
    return size


def receive_file(sock, path, header, *, checkpoint=lambda: None, progress=None,
                 buffer_size=DEFAULT_HTTP_TRANSFER_BUFFER_SIZE):
    size = header.get('size')
    if type(size) is not int or size < 0:
        raise ValueError('Invalid declared file size')
    digest = hashlib.sha256()
    received = 0
    with open(path, 'wb') as target:
        while received < size:
            checkpoint()
            chunk = sock.recv(min(buffer_size, size - received))
            if not chunk:
                raise ConnectionError('Incomplete file stream')
            target.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            if progress:
                progress(received, size)
        trailer = receive_control(sock)
        if trailer.get('sha256') != digest.hexdigest():
            raise ValueError('File checksum mismatch')
    checkpoint()
    return size
