"""Server-initiated TCP connection to a listening Python Client."""
import socket
import threading

from server.runtime.session_acceptor import SessionAcceptor


class BindConnector:
    def __init__(self, server):
        self.server = server
        self._acceptor = SessionAcceptor(server)
        self._lock = threading.Lock()
        self._inflight = set()
        self._sessions = {}

    @staticmethod
    def _endpoint(host, port):
        if not isinstance(host, str) or not host.strip() or host != host.strip():
            raise ValueError('Enter a Client host or IP address')
        if any(char.isspace() for char in host) or len(host) > 253:
            raise ValueError('Invalid Client host')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Port must be between 1 and 65535')
        return host, port

    def _current_session(self, endpoint):
        session = self._sessions.get(endpoint)
        return session if session is not None and session in self.server.connections else None

    def connect(self, host, port):
        host, port = self._endpoint(host, port)
        endpoint = (host.lower(), port)
        with self._lock:
            if endpoint in self._inflight:
                raise RuntimeError('Connection already in progress')
            active = self._current_session(endpoint)
            if active is not None:
                return active
            self._inflight.add(endpoint)
        try:
            sock = socket.create_connection((host, port), timeout=5)
            try:
                session = self._acceptor.accept_session(
                    sock, sock.getpeername(), protocol='bind_tcp',
                    strict_registration=True, raise_on_error=True,
                )
            except Exception:
                sock.close()
                raise
            with self._lock:
                self._sessions[endpoint] = session
            return session
        finally:
            with self._lock:
                self._inflight.discard(endpoint)

    def disconnect(self, client_id):
        with self._lock:
            session = next((s for s in self._sessions.values()
                            if s.session_info.client_id == client_id
                            and s in self.server.connections), None)
            if session is None:
                raise ValueError('Bind Client is not connected')
        # Close the session socket, not the listener or Client process.
        try:
            session.transport.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        session.close()
        return client_id
