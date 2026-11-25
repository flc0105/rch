"""Socket endpoint; each instance owns one listening socket and its lifecycle."""
import errno
import socket
import ssl
import threading
import time

from core.protocol.rchsocket import RCHSocket
from core.protocol.file_stream import DATA_GREETING
from core.utils.logger import logger
from server.runtime.session_acceptor import SessionAcceptor


class ServerListener(SessionAcceptor):
    _CLOSED_SOCKET_ERRNOS = {
        errno.EBADF, errno.EINVAL, getattr(errno, 'ENOTSOCK', 88), 10038,
    }

    def __init__(self, server, config: dict, ssl_context=None, verify_peer=None):
        super().__init__(server)
        self.config = dict(config)
        self.listener_id = self.config.get('id', 'tcp-default')
        self.name = self.config.get('name', 'TCP')
        self.protocol = self.config.get('protocol', 'tcp')
        self.address = (self.config['host'], int(self.config['port']))
        self.socket = RCHSocket()
        self.ssl_context = ssl_context
        self.verify_peer = verify_peer
        self._tunnel_handler = None
        self._stop_event = threading.Event()
        self._thread = None

    def set_tunnel_handler(self, handler):
        """Opt-in accept hook. None restores the original handshake verbatim."""
        self._tunnel_handler = handler

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
                if self.verify_peer is not None:
                    self.verify_peer(raw_sock.getpeercert(binary_form=True))
                # A handshake deadline must not become the application's read timeout.
                raw_sock.settimeout(None)
            except (OSError, ssl.SSLError) as exc:
                logger.warning('mTLS handshake or identity verification failed on %s from %s: %s', self.listener_id, addr, exc)
                raw_sock.close()
                return None
        handler = self._tunnel_handler
        if handler is not None:
            handler.dispatch_server(self, raw_sock, addr)
            return None
        try:
            packet, transport = self._receive_client_info(raw_sock, addr)
            return self.route_accepted_connection(raw_sock, addr, packet, transport)
        except Exception as exc:
            raw_sock.close()
            logger.error('Failed client handshake from %s: %s', addr, exc)
            return None

    def route_accepted_connection(self, raw_sock, addr, packet, transport):
        if isinstance(packet, dict) and packet.get('type') == DATA_GREETING:
            web = getattr(self.server, 'web_service', None)
            service = getattr(getattr(web, 'transfer_api', None), 'transfer_service', None)
            handler = getattr(service, 'tcp_transport', None)
            if handler is not None:
                handler.accept_reverse(raw_sock, packet, self)
            else:
                raw_sock.close()
            return None
        return self.accept_session(raw_sock, addr, initial_handshake=(packet, transport),
                                   listener_id=self.listener_id, listener_name=self.name,
                                   listener_port=self.address[1], protocol=self.protocol)

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
