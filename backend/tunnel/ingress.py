"""Opt-in shared-port TCP handshake adapter, removable from both RCH listeners.

The normal RCH connection has no Tunnel handshake path while this adapter is
unmounted. The first frame on a Tunnel socket uses the existing RCH length/JSON
framing solely for routing; all subsequent frames/data use the Tunnel protocol
on independent sockets, never on the RCH session socket.
"""
import json
import select
import socket
import struct
import threading

from core.protocol.rchsocket import RCHSocket
from tunnel.transport import close_socket
from core.protocol.auxiliary import receive_greeting

HELLO_TYPE = 'rch_tunnel'
_MAX_HELLO = 4096


def send_hello(sock, *, client_id, role, token, stream_id=None):
    data = {'type': HELLO_TYPE, 'client_id': client_id, 'role': role, 'token': token}
    if stream_id is not None:
        data['id'] = stream_id
    payload = json.dumps(data, separators=(',', ':')).encode('utf-8')
    if len(payload) > _MAX_HELLO:
        raise ValueError('Tunnel greeting too large')
    sock.sendall(struct.pack(RCHSocket.HEADER_FORMAT, len(payload)) + payload)


def receive_hello(sock):
    """Bind-side only: ordinary Bind connections send no first packet."""
    sock.settimeout(5)
    try:
        header = _read_exact(sock, RCHSocket.HEADER_SIZE)
        length = struct.unpack(RCHSocket.HEADER_FORMAT, header)[0]
        if not 0 < length <= _MAX_HELLO:
            raise ValueError('Invalid Tunnel greeting length')
        message = json.loads(_read_exact(sock, length))
        if not isinstance(message, dict) or message.get('type') != HELLO_TYPE:
            raise ValueError('Unknown Bind connection greeting')
        return message
    finally:
        sock.settimeout(None)


def _read_exact(sock, length):
    result = bytearray()
    while len(result) < length:
        data = sock.recv(length - len(result))
        if not data:
            raise ConnectionError('Tunnel greeting closed')
        result.extend(data)
    return bytes(result)


class SharedPortHandler:
    """Routes only registered clients; no active registrations -> unmount."""

    def __init__(self):
        self._lock = threading.RLock()
        self._receivers = {}
        self._handshake_slots = threading.BoundedSemaphore(64)

    def register(self, client_id, receiver):
        with self._lock:
            if client_id in self._receivers and self._receivers[client_id] is not receiver:
                raise ValueError('Tunnel receiver already registered for Client')
            self._receivers[client_id] = receiver

    def unregister(self, client_id, receiver):
        with self._lock:
            if self._receivers.get(client_id) is receiver:
                del self._receivers[client_id]

    @property
    def empty(self):
        with self._lock:
            return not self._receivers

    def dispatch_server(self, listener, conn, addr):
        self._dispatch(self.accept_server, conn, listener, conn, addr)

    def dispatch_bind(self, listener, conn):
        self._dispatch(self.accept_bind, conn, listener, conn)

    def _dispatch(self, handler, sock, *args):
        # A stalled greeting cannot grow unbounded handshake threads. This
        # semaphore and its threads exist only while a Tunnel is active.
        if not self._handshake_slots.acquire(blocking=False):
            close_socket(sock)
            return
        def run():
            try:
                handler(*args)
            finally:
                self._handshake_slots.release()
        try:
            threading.Thread(target=run, daemon=True, name='TunnelHandshake').start()
        except Exception:
            self._handshake_slots.release()
            close_socket(sock)
            raise

    def _route(self, conn, packet):
        try:
            client_id = packet.get('client_id')
            with self._lock:
                receiver = self._receivers.get(client_id)
            if receiver is None:
                raise ValueError('Unknown Tunnel Client')
            receiver.accept(conn, packet)
        except (OSError, ValueError, TypeError, ConnectionError):
            close_socket(conn)

    def accept_server(self, listener, conn, addr):
        """Read first RCH-framed packet once; pass normal sessions untouched."""
        try:
            packet, transport = listener._receive_client_info(conn, addr)
            if isinstance(packet, dict) and packet.get('type') == HELLO_TYPE:
                self._route(conn, packet)
                return
            listener.route_accepted_connection(conn, addr, packet, transport)
        except (OSError, ValueError, TypeError, ConnectionError):
            close_socket(conn)

    def accept_bind(self, listener, conn):
        """Bind's normal Server is silent first; Tunnel proactively sends hello.

        This short wait runs only while a Tunnel is active and on a separate
        thread, never in the Bind accept loop. An already occupied RCH session
        gives a late-arriving Tunnel hello enough time to arrive.
        """
        try:
            with listener._lock:
                occupied = listener._occupied
            readable, _, _ = select.select([conn], [], [], 2 if occupied else 0.25)
            if not readable:
                listener._offer_session(conn)
                return
            packet = receive_greeting(conn)
            if packet.get('type') == HELLO_TYPE:
                self._route(conn, packet)
            else:
                listener.route_auxiliary_connection(conn, packet)
        except (OSError, ValueError, TypeError, ConnectionError):
            close_socket(conn)
