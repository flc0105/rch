import json
import socket
import struct
import threading


class RCHSocket:
    HEADER_FORMAT = 'i'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(self, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        self.socket = socket.socket(family, type, proto)
        self._send_lock = threading.RLock()

    def connect(self, address: tuple) -> bool:
        result = self.socket.connect_ex(address)
        return result == 0

    def bind(self, address: tuple, backlog: int = 5) -> None:
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(address)
        self.socket.listen(backlog)

    def accept(self) -> tuple:
        return self.socket.accept()

    def shutdown(self) -> None:
        self.socket.shutdown(socket.SHUT_RDWR)

    def close(self) -> None:
        self.socket.close()

    def send(self, data: dict) -> None:
        encoded = json.dumps(data).encode()
        with self._send_lock:
            self._send_packet(encoded)

    def recv(self) -> dict:
        data = self._recv_packet()
        return json.loads(data.decode())

    def _send_packet(self, data: bytes) -> None:
        self.socket.sendall(struct.pack(self.HEADER_FORMAT, len(data)))
        self.socket.sendall(data)

    def _recv_packet(self) -> bytes:
        header = self._recv_exactly(self.HEADER_SIZE)
        length = struct.unpack(self.HEADER_FORMAT, header)[0]
        return self._recv_exactly(length)

    def _recv_exactly(self, size: int) -> bytes:
        chunks = []
        bytes_remaining = size

        while bytes_remaining > 0:
            chunk = self.socket.recv(bytes_remaining)
            if not chunk:
                if bytes_remaining == size:
                    raise socket.error('Connection closed')
                raise socket.error('Connection aborted')
            chunks.append(chunk)
            bytes_remaining -= len(chunk)

        return b''.join(chunks)






