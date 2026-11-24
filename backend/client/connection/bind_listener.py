"""Python Client Bind TCP listener.

The listener belongs to the process; the accepted socket belongs to a session.
One session at a time is admitted, with reconnection after it ends.
"""
import queue
import socket
import threading
from contextlib import contextmanager

from client.connection.file_connection_slot import FileConnectionSlot
from core.protocol.auxiliary import close_socket, receive_greeting
from core.protocol.file_stream import DATA_GREETING

from core.utils.logger import logger

_active_listener = None


def current_bind_listener():
    return _active_listener


class BindListener:
    def __init__(self, config):
        if config.get('connection_mode') != 'bind':
            raise ValueError('Bind listener requires connection_mode=bind')
        self.host = str(config.get('bind_host') or '').strip()
        if not self.host:
            raise ValueError('Bind listener requires a host')
        port = config.get('bind_port')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('bind_port must be an integer between 1 and 65535')
        self.address = (self.host, port)
        self._lock = threading.Lock()
        self._accepting = True
        self._occupied = False
        self._pending = queue.Queue(maxsize=1)
        self._socket = None
        self._thread = None
        self._stop = threading.Event()
        self._tunnel_handler = None
        self._file_slots = {}
        self._file_handshakes = threading.BoundedSemaphore(32)

    def start(self):
        with self._lock:
            if self._socket is not None:
                return
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # POSIX: reclaim the same address after an old TCP session enters
                # TIME_WAIT. SO_REUSEADDR does not allow two active TCP listeners
                # on the same address (that would require SO_REUSEPORT).
                # Windows: keep exclusive bind semantics, never use SO_REUSEADDR.
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(self.address)
                sock.listen(1)
                sock.settimeout(0.25)
            except Exception:
                sock.close()
                raise
            global _active_listener
            _active_listener = self
            self._socket = sock
            self._thread = threading.Thread(target=self._accept_loop, args=(sock,), daemon=True,
                                            name='RCHBindTcpListener')
            self._thread.start()
        logger.info('Bind TCP listening on %s:%s', *self.address)
        from client.update.signals import report_ready
        report_ready('', 'bind')

    def _accept_loop(self, listener_socket):
        while not self._stop.is_set():
            try:
                conn, peer = listener_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    logger.exception('Bind TCP listener stopped unexpectedly')
                break
            handler = self._tunnel_handler
            if handler is not None:
                handler.dispatch_bind(self, conn)
                continue
            with self._lock:
                has_file_slots = self._occupied and bool(self._file_slots)
            if has_file_slots:
                self._dispatch_file_connection(conn)
            else:
                self._offer_session(conn)

    def _offer_session(self, conn):
        with self._lock:
            allowed = (self._accepting and not self._occupied
                       and not self._stop.is_set())
            if allowed:
                self._occupied = True
                self._pending.put_nowait(conn)
        if not allowed:
            conn.close()

    def _sync_backlog(self):
        if self._socket is not None:
            self._socket.listen(64 if self._tunnel_handler is not None or self._file_slots else 1)

    def set_tunnel_handler(self, handler):
        """Keep normal Bind admission unchanged when no auxiliary connection is expected."""
        with self._lock:
            self._tunnel_handler = handler
            self._sync_backlog()

    @contextmanager
    def expect_file_connection(self, transfer_id, token):
        slot = FileConnectionSlot(token)
        with self._lock:
            if not self._occupied or not self._accepting or self._stop.is_set():
                raise ConnectionError('Bind session is not active')
            if transfer_id in self._file_slots or len(self._file_slots) >= 32:
                raise RuntimeError('Too many pending file connections or duplicate transfer')
            self._file_slots[transfer_id] = slot
            self._sync_backlog()
        try:
            yield slot
        finally:
            with self._lock:
                if self._file_slots.get(transfer_id) is slot:
                    self._file_slots.pop(transfer_id, None)
                    self._sync_backlog()
            slot.close()

    def route_auxiliary_connection(self, conn, packet):
        if packet.get('type') != DATA_GREETING:
            raise ValueError('Unknown auxiliary connection')
        self.accept_file_connection(conn, packet)

    def accept_file_connection(self, conn, packet):
        """Called by the same-port greeting router; the slot owns accepted sockets."""
        with self._lock:
            slot = self._file_slots.get(packet.get('transfer_id')) if self._occupied else None
            if slot is not None and slot.offer(conn, packet.get('token')):
                return
        close_socket(conn)

    def _dispatch_file_connection(self, conn):
        if not self._file_handshakes.acquire(blocking=False):
            close_socket(conn)
            return
        def run():
            try:
                packet = receive_greeting(conn)
                self.route_auxiliary_connection(conn, packet)
            except (OSError, ValueError, TypeError, ConnectionError):
                close_socket(conn)
            finally:
                self._file_handshakes.release()
        try:
            threading.Thread(target=run, daemon=True, name='FileDataHandshake').start()
        except Exception:
            self._file_handshakes.release()
            close_socket(conn)
            raise

    def _clear_file_slots(self):
        slots = list(self._file_slots.values())
        self._file_slots.clear()
        self._sync_backlog()
        for slot in slots:
            slot.close()

    def accept(self):
        while not self._stop.is_set():
            try:
                conn = self._pending.get(timeout=0.25)
            except queue.Empty:
                if self._thread is not None and not self._thread.is_alive():
                    raise OSError('Bind TCP listener stopped')
                continue
            with self._lock:
                enabled = self._accepting and not self._stop.is_set()
            if enabled:
                conn.settimeout(None)
                return conn
            conn.close()
            self.release_session()
        raise OSError('Bind TCP listener closed')

    def set_accepting(self, enabled):
        with self._lock:
            self._accepting = bool(enabled)
            if not enabled:
                while True:
                    try:
                        pending = self._pending.get_nowait()
                    except queue.Empty:
                        break
                    pending.close()
                self._occupied = False
                self._clear_file_slots()

    def release_session(self):
        with self._lock:
            self._occupied = False
            self._clear_file_slots()

    def close(self):
        global _active_listener
        if _active_listener is self:
            _active_listener = None
        self._tunnel_handler = None
        self._stop.set()
        self.set_accepting(False)
        with self._lock:
            sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
