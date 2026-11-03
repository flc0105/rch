"""Socket endpoint; each instance owns one listening socket and its lifecycle."""
import errno
import socket
import ssl
import threading
import time

from core.protocol.rchsocket import RCHSocket
from core.utils.logger import logger
from server.runtime.session_acceptor import SessionAcceptor


class ServerListener(SessionAcceptor):
    _CLOSED_SOCKET_ERRNOS = {
        errno.EBADF, errno.EINVAL, getattr(errno, 'ENOTSOCK', 88), 10038,
    }

    def __init__(self, server, config=None, ssl_context=None):
        super().__init__(server)
        self.config = dict(config or {})
        self.listener_id = self.config.get('id', 'tcp-default')
        self.name = self.config.get('name', 'TCP')
        self.protocol = self.config.get('protocol', 'tcp')
        self.address = (self.config.get('host', server.address[0] if hasattr(server, 'address') else ''),
                        int(self.config.get('port', server.address[1] if hasattr(server, 'address') else 9999)))
        self.socket = RCHSocket() if config or not hasattr(server, 'socket') else server.socket
        self.ssl_context = ssl_context
        self._stop_event = threading.Event()
        self._thread = None

    def stop(self):
        """Stop accepting new sessions; existing sessions remain active."""
        self._stop_event.set()
        try:
            self.socket.shutdown()
        except OSError:
            pass
        try:
            self.socket.close()
        except OSError:
            pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)

    def _is_closed_socket_error(self, exc):
        return getattr(exc, 'errno', None) in self._CLOSED_SOCKET_ERRNOS

    def _bind_server_socket(self):
        self.socket.bind(self.address)
        logger.info('Listener %s (%s) on %s:%s', self.listener_id, self.protocol, *self.address)

    def start(self):
        """Bind synchronously so failures are visible to the API caller."""
        self._bind_server_socket()
        self._thread = threading.Thread(target=self.serve, kwargs={'already_bound': True},
                                        daemon=True, name=f'listener-{self.listener_id}')
        self._thread.start()

    def _accept_connection(self):
        raw_sock, addr = self.socket.accept()
        if self.ssl_context is not None:
            try:
                raw_sock.settimeout(5)
                raw_sock = self.ssl_context.wrap_socket(raw_sock, server_side=True)
            except (OSError, ssl.SSLError) as exc:
                logger.warning('TLS handshake failed on %s from %s: %s', self.listener_id, addr, exc)
                raw_sock.close()
                return None
        return self.accept_session(raw_sock, addr, listener_id=self.listener_id,
                                   listener_name=self.name, protocol=self.protocol)

    def serve(self, already_bound=False):
        if not already_bound:
            try:
                self._bind_server_socket()
            except OSError as exc:
                logger.error('Listener bind failed: %s', exc)
                return
        while not self._stop_event.is_set():
            try:
                self._accept_connection()
            except OSError as exc:
                if self._stop_event.is_set() or self._is_closed_socket_error(exc):
                    break
                logger.error('Listener accept error: %s', exc)
                time.sleep(0.1)
