"""Server-initiated TCP connection to a listening Python Client."""
import socket
import threading
import time

from server.runtime.session_acceptor import SessionAcceptor
from server.application.connection.bind_web_endpoint import validate_web_origin


class BindConnector:
    def __init__(self, server):
        self.server = server
        self._acceptor = SessionAcceptor(server)
        self._lock = threading.Lock()
        self._inflight = set()
        self._sessions = {}
        self._reconnect_until = {}
        self._reconnecting_targets = set()

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

    def connect(self, host, port, *, server_web_base_url='', transport='tcp'):
        session, _ = self.connect_with_status(host, port, server_web_base_url=server_web_base_url, transport=transport)
        return session

    def connect_with_status(self, host, port, *, server_web_base_url='', transport='tcp'):
        host, port = self._endpoint(host, port)
        if transport not in ('tcp', 'mtls_tcp'):
            raise ValueError('Unknown Bind transport')
        announced_url = validate_web_origin(server_web_base_url) if server_web_base_url else ''
        endpoint = (host.lower(), port)
        with self._lock:
            if endpoint in self._inflight:
                raise RuntimeError('Connection already in progress')
            active = self._current_session(endpoint)
            if active is not None:
                if getattr(active, 'bind_transport', 'tcp') != transport:
                    raise ValueError('Connected Bind transport does not match request')
                return active, True
            self._inflight.add(endpoint)
            deadline = self._reconnect_until.pop(endpoint, 0)
        try:
            return self._dial(host, port, announced_url, deadline, transport=transport), False
        finally:
            with self._lock:
                self._inflight.discard(endpoint)

    def _dial(self, host, port, announced_url, deadline, *, target_id='', transport='tcp'):
        endpoint = (host.lower(), port)
        # The Client may still be releasing the previous accepted session
        # when the operator immediately clicks Connect again. Wait briefly
        # for its existing listener instead of surfacing a transient close.
        while True:
            sock = None
            try:
                sock = socket.create_connection((host, port), timeout=5)
                if transport == 'mtls_tcp':
                    sock = self.server.listener_manager.identities.wrap_outbound_socket(sock)
                session = self._acceptor.accept_session(
                    sock, sock.getpeername(), protocol='bind_tcp',
                    strict_registration=True, raise_on_error=True,
                    initialize_session=lambda session: (setattr(session, 'server_web_base_url', announced_url),
                                                        setattr(session, 'bind_dial_endpoint', (host, port)),
                                                        setattr(session, 'bind_transport', transport),
                                                        setattr(session, 'saved_bind_target_id', target_id)),
                )
                with self._lock:
                    self._sessions[endpoint] = session
                return session
            except OSError:
                if sock is not None:
                    sock.close()
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
            except Exception:
                if sock is not None:
                    sock.close()
                raise

    def run_if_offline(self, host, port, callback, *, target_id=''):
        endpoint = (host.lower(), port)
        with self._lock:
            if (endpoint in self._inflight or self._current_session(endpoint) is not None
                    or (target_id and target_id in self._reconnecting_targets)):
                raise ValueError('Disconnect the connection before removing it')
            return callback()

    def reconnect(self, client_id):
        with self._lock:
            session = next((s for s in self._sessions.values()
                            if s.session_info.client_id == client_id
                            and s in self.server.connections), None)
            if session is None:
                raise ValueError('Bind Client is not connected')
            host, port = session.bind_dial_endpoint
            endpoint = (host.lower(), port)
            if endpoint in self._inflight:
                raise RuntimeError('Connection already in progress')
            announced_url = session.server_web_base_url
            target_id = getattr(session, 'saved_bind_target_id', '')
            transport = getattr(session, 'bind_transport', 'tcp')
            self._inflight.add(endpoint)
            if target_id:
                self._reconnecting_targets.add(target_id)
            self._sessions.pop(endpoint, None)
        try:
            self._close_session(session)
            # Wait until the old session's cleanup and registry removal finish.
            deadline = time.monotonic() + 5.0
            while session in self.server.connections:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Previous connection is still closing; try Connect again')
                time.sleep(0.05)
            return self._dial(host, port, announced_url, time.monotonic() + 2.0,
                              target_id=target_id, transport=transport)
        finally:
            with self._lock:
                self._inflight.discard(endpoint)
                self._reconnecting_targets.discard(target_id)

    def disconnect(self, client_id):
        with self._lock:
            session = next((s for s in self._sessions.values()
                            if s.session_info.client_id == client_id
                            and s in self.server.connections), None)
            if session is None:
                raise ValueError('Bind Client is not connected')
            # A new Connect must not see the just-disconnected session as active.
            removed = [endpoint for endpoint, active in self._sessions.items() if active is session]
            for endpoint in removed:
                del self._sessions[endpoint]
                self._reconnect_until[endpoint] = time.monotonic() + 2.0
        self._close_session(session)
        return client_id

    @staticmethod
    def _close_session(session):
        # Record an intentional Server disconnect before shutting down the
        # socket: SessionAcceptor observes the close on another thread.
        session.note_server_disconnect('disconnect')
        # Close the session socket, not the listener or Client process.
        try:
            session.transport.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        session.close()
