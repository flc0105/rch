"""Process-scoped, opt-in Client ingress for Server-initiated TCP forwarding."""
import secrets
import socket
import threading

from tunnel.transport import bridge, close_socket, listen, recv_frame, send_frame


class _Front:
    def __init__(self, name, listener):
        self.name = name
        self.listener = listener
        self.streams = set()
        self.active = True


class ClientTunnel:
    def __init__(self):
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._ingress = None
        self._port = None
        self._token = None
        self._control = None
        self._fronts = {}
        self._waiting = {}
        self._stop = threading.Event()

    def start(self, *, name, listen_host, listen_port, channel_port, token):
        if not isinstance(token, str) or len(token) != 64:
            raise ValueError('Invalid tunnel token')
        with self._lock:
            if name in self._fronts:
                raise ValueError(f'Tunnel mapping already exists: {name}')
            if self._ingress is not None and (self._port != channel_port or self._token != token):
                if self._control is not None:
                    raise ValueError('Existing tunnel uses another channel/token')
                # The former Server process has gone away. A fresh operator
                # start replaces its unreachable listeners and control token.
                for old_name in tuple(self._fronts):
                    self.stop(old_name)
            first = self._ingress is None
            if first:
                ingress = listen('0.0.0.0', channel_port)
                self._ingress, self._port, self._token = ingress, channel_port, token
                self._stop.clear()
            try:
                front_sock = listen(listen_host, listen_port)
            except Exception:
                if first:
                    close_socket(self._ingress)
                    self._ingress = self._port = self._token = None
                raise
            front = _Front(name, front_sock)
            self._fronts[name] = front
            if first:
                threading.Thread(target=self._accept_ingress, args=(self._ingress,), daemon=True,
                                 name='TunnelIngress').start()
            threading.Thread(target=self._accept_front, args=(front,), daemon=True,
                             name=f'TunnelFront-{name}').start()
            return {'name': name, 'listen': f'{listen_host}:{listen_port}', 'channel_port': channel_port}

    def stop(self, name):
        with self._lock:
            front = self._fronts.pop(name, None)
            if front is None:
                raise ValueError(f'No tunnel mapping named {name}')
            front.active = False
            close_socket(front.listener)
            for sock in tuple(front.streams):
                close_socket(sock)
            for stream_id, (event, _slot, owner) in tuple(self._waiting.items()):
                if owner is front:
                    self._waiting.pop(stream_id, None)
                    event.set()
            if not self._fronts:
                self._stop.set()
                close_socket(self._control)
                close_socket(self._ingress)
                self._control = self._ingress = self._token = self._port = None
            return {'name': name, 'stopped': True}

    def _accept_ingress(self, ingress):
        while not self._stop.is_set():
            try:
                sock, _ = ingress.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._register_ingress, args=(sock,), daemon=True,
                             name='TunnelIngressHandshake').start()

    def _register_ingress(self, sock):
        try:
            sock.settimeout(5)
            packet = recv_frame(sock)
            if not secrets.compare_digest(str(packet.get('token') or ''), str(self._token or '')):
                raise ValueError('Invalid tunnel token')
            role = packet.get('role')
            with self._lock:
                if self._stop.is_set():
                    raise ConnectionError('Tunnel stopped')
                if role == 'control':
                    if self._control is not None:
                        raise ValueError('Control connection already active')
                    send_frame(sock, {'ok': True})
                    self._control = sock
                    sock.settimeout(None)
                    threading.Thread(target=self._control_reader, args=(sock,), daemon=True,
                                     name='TunnelClientControl').start()
                    return
                if role != 'data':
                    raise ValueError('Unsupported tunnel ingress role')
                stream_id = packet.get('id')
                pending = self._waiting.pop(stream_id, None) if isinstance(stream_id, str) else None
                if pending is None:
                    raise ValueError('Unknown or expired stream')
                event, slot, _front = pending
                try:
                    send_frame(sock, {'ok': True})
                    sock.settimeout(None)
                    slot.append(sock)
                finally:
                    event.set()
                return
        except (OSError, ValueError, ConnectionError, KeyError):
            pass
        close_socket(sock)

    def _control_reader(self, sock):
        try:
            while True:
                packet = recv_frame(sock)
                if packet.get('op') == 'reject':
                    with self._lock:
                        pending = self._waiting.pop(packet.get('id'), None)
                    if pending is not None:
                        pending[0].set()
        except (OSError, ConnectionError, ValueError):
            pass
        finally:
            with self._lock:
                if self._control is sock:
                    self._control = None
            close_socket(sock)

    def _accept_front(self, front):
        while front.active and not self._stop.is_set():
            try:
                sock, _ = front.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_front, args=(front, sock), daemon=True,
                             name='TunnelStream').start()

    def _handle_front(self, front, sock):
        event = threading.Event()
        slot = []
        stream_id = secrets.token_hex(16)
        with self._lock:
            if (not front.active or self._control is None or len(self._waiting) >= 128
                    or sum(len(item.streams) for item in self._fronts.values()) >= 256):
                close_socket(sock)
                return
            front.streams.add(sock)
            self._waiting[stream_id] = (event, slot, front)
            control = self._control
        try:
            send_frame(control, {'op': 'open', 'id': stream_id, 'name': front.name}, self._send_lock)
            if not event.wait(10) or not slot:
                return
            with self._lock:
                front.streams.add(slot[0])
            bridge(sock, slot[0])
        except OSError:
            pass
        finally:
            with self._lock:
                self._waiting.pop(stream_id, None)
                front.streams.discard(sock)
                if slot:
                    front.streams.discard(slot[0])
            close_socket(sock)
            if slot:
                close_socket(slot[0])


_manager = None
_manager_lock = threading.Lock()


def manager():
    """Importing the action handler alone does not start any listeners/threads."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ClientTunnel()
        return _manager


def execute(scope, action, payload):
    from core.protocol.control import TunnelAction
    from client.config.config import RUNTIME_CONFIG
    if RUNTIME_CONFIG.get('connection_mode') != 'bind':
        return 0, 'Tunnel requires a Bind Client'
    scope._checkpoint()
    try:
        if action == TunnelAction.START:
            result = manager().start(**payload)
        elif action == TunnelAction.STOP:
            result = manager().stop(payload['name'])
        else:
            return 0, 'Unsupported tunnel action'
        return 1, result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return 0, str(exc)
