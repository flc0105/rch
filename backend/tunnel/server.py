"""Server-side process-scoped forwarding peers; independent of RCH session lifetime."""
import secrets
import socket
import threading

from tunnel.transport import bridge, close_socket, recv_frame, send_frame


class ServerPeer:
    def __init__(self, client_id, host, channel_port, token):
        self.client_id = client_id
        self.host = host
        self.channel_port = channel_port
        self.token = token
        self.mappings = {}
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._control = None
        self._streams = set()
        self._closed = False
        self.last_error = ''

    def attach(self):
        sock = socket.create_connection((self.host, self.channel_port), timeout=5)
        try:
            send_frame(sock, {'role': 'control', 'token': self.token})
            reply = recv_frame(sock)
            if reply.get('ok') is not True:
                raise ConnectionError('Tunnel control registration refused')
            sock.settimeout(None)
            with self._lock:
                if self._closed:
                    raise ConnectionError('Tunnel stopped')
                self._control = sock
            threading.Thread(target=self._read_control, args=(sock,), daemon=True,
                             name='TunnelServerControl').start()
        except Exception:
            close_socket(sock)
            raise

    @property
    def connected(self):
        with self._lock:
            return self._control is not None and not self._closed

    def _read_control(self, sock):
        try:
            while True:
                message = recv_frame(sock)
                if message.get('op') != 'open':
                    raise ValueError('Unknown tunnel control message')
                stream_id = message.get('id')
                name = message.get('name')
                with self._lock:
                    target = self.mappings.get(name)
                if (not isinstance(stream_id, str) or len(stream_id) != 32
                        or target is None):
                    self._reject(stream_id)
                    continue
                threading.Thread(target=self._open_stream, args=(stream_id, target[0]), daemon=True,
                                 name='TunnelServerStream').start()
        except (OSError, ConnectionError, ValueError) as exc:
            with self._lock:
                self.last_error = str(exc)
        finally:
            with self._lock:
                if self._control is sock:
                    self._control = None
            close_socket(sock)

    def _reject(self, stream_id):
        with self._lock:
            sock = self._control
        if sock is not None:
            try:
                send_frame(sock, {'op': 'reject', 'id': stream_id}, self._send_lock)
            except OSError:
                pass

    def _open_stream(self, stream_id, target):
        remote = data = None
        try:
            remote = socket.create_connection(target, timeout=8)
            data = socket.create_connection((self.host, self.channel_port), timeout=8)
            send_frame(data, {'role': 'data', 'token': self.token, 'id': stream_id})
            if recv_frame(data).get('ok') is not True:
                raise ConnectionError('Tunnel data registration failed')
            remote.settimeout(None)
            data.settimeout(None)
            with self._lock:
                if self._closed:
                    return
                self._streams.update((remote, data))
            bridge(remote, data)
        except (OSError, ValueError, ConnectionError) as exc:
            with self._lock:
                self.last_error = str(exc)
            self._reject(stream_id)
        finally:
            with self._lock:
                self._streams.discard(remote)
                self._streams.discard(data)
            close_socket(remote)
            close_socket(data)

    def close(self):
        with self._lock:
            self._closed = True
            sock, self._control = self._control, None
            connections = tuple(self._streams)
            self.mappings.clear()
        close_socket(sock)
        for stream in connections:
            close_socket(stream)

    def snapshot(self):
        with self._lock:
            return {
                'client_id': self.client_id,
                'host': self.host,
                'channel_port': self.channel_port,
                'connected': self._control is not None and not self._closed,
                'streams': len(self._streams) // 2,
                'last_error': self.last_error,
                'mappings': [dict(name=name, target_host=target[0], target_port=target[1],
                                  **frontend) for name, (target, frontend) in self.mappings.items()],
            }


class ServerTunnels:
    def __init__(self):
        self._lock = threading.RLock()
        self._peers = {}

    def prepare(self, client_id, host, channel_port, name):
        with self._lock:
            peer = self._peers.get(client_id)
            if peer is not None:
                if not peer.connected or peer.host != host or peer.channel_port != channel_port:
                    raise ValueError('Tunnel peer unavailable or configured differently; stop existing mappings first')
                if name in peer.mappings:
                    raise ValueError(f'Tunnel mapping already exists: {name}')
                return peer, False
            peer = ServerPeer(client_id, host, channel_port, secrets.token_hex(32))
            self._peers[client_id] = peer
            return peer, True

    def ready(self, client_id, peer, name, target_host, target_port, listen_host, listen_port, *, first):
        try:
            if first:
                peer.attach()
            with peer._lock:
                if not peer.connected:
                    raise ConnectionError('Tunnel control channel closed')
                peer.mappings[name] = ((target_host, target_port), {
                    'listen_host': listen_host, 'listen_port': listen_port,
                })
        except Exception:
            self.discard_if_empty(client_id, peer)
            raise

    def discard_if_empty(self, client_id, peer):
        with self._lock:
            if self._peers.get(client_id) is peer and not peer.mappings:
                del self._peers[client_id]
                peer.close()

    def stopped(self, client_id, name):
        with self._lock:
            peer = self._peers.get(client_id)
            if peer is None or name not in peer.mappings:
                raise ValueError(f'No tunnel mapping named {name}')
            del peer.mappings[name]
            self.discard_if_empty(client_id, peer)

    def peer(self, client_id):
        with self._lock:
            return self._peers.get(client_id)

    def list(self, client_id):
        peer = self.peer(client_id)
        return peer.snapshot() if peer is not None else {
            'client_id': client_id, 'connected': False, 'streams': 0, 'mappings': [],
        }


_manager_lock = threading.Lock()

def manager_for(server):
    """Lazy server-owned instance: no dedicated process or background task until start."""
    with _manager_lock:
        if not hasattr(server, '_tcp_tunnels'):
            server._tcp_tunnels = ServerTunnels()
        return server._tcp_tunnels
