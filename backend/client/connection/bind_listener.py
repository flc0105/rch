"""Python Client Bind TCP listener.

The listener belongs to the process; the accepted socket belongs to a session.
One session at a time is admitted, with reconnection after it ends.
"""
import queue
import socket
import threading

from core.utils.logger import logger


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

    def start(self):
        with self._lock:
            if self._socket is not None:
                return
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Never use SO_REUSEADDR to share a port with a second process.
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(self.address)
                sock.listen(1)
                sock.settimeout(0.25)
            except Exception:
                sock.close()
                raise
            self._socket = sock
            self._thread = threading.Thread(target=self._accept_loop, args=(sock,), daemon=True,
                                            name='RCHBindTcpListener')
            self._thread.start()
        logger.info('Bind TCP listening on %s:%s', *self.address)

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
            with self._lock:
                allowed = (self._accepting and not self._occupied
                           and not self._stop.is_set())
                if allowed:
                    self._occupied = True
                    self._pending.put_nowait(conn)
            if not allowed:
                conn.close()

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

    def release_session(self):
        with self._lock:
            self._occupied = False

    def close(self):
        self._stop.set()
        self.set_accepting(False)
        with self._lock:
            sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
