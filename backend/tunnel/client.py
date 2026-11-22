"""Passive shared-listener Tunnel endpoint and lazy Python Client Control adapter.

A passive endpoint never opens a channel listening port. The established RCH
listener supplies each separately accepted, authenticated TCP socket.
"""
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


class PassiveTunnel:
    def __init__(self, token):
        if not isinstance(token, str) or len(token) != 64:
            raise ValueError('Invalid Tunnel token')
        self.token = token
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._control = None
        self._fronts = {}
        self._targets = {}
        self._waiting = {}
        self._target_waiting = {}
        self._streams = set()
        self._closed = False
        self.last_error = ''

    @property
    def connected(self):
        with self._lock:
            return self._control is not None and not self._closed

    @property
    def empty(self):
        with self._lock:
            return not self._fronts and not self._targets

    def add(self, name, *, exposed, listen_host, listen_port, target_host, target_port):
        with self._lock:
            if self._closed or name in self._fronts or name in self._targets:
                raise ValueError('Duplicate or closed Tunnel mapping')
            if exposed:
                front = _Front(name, listen(listen_host, listen_port))
                self._fronts[name] = front
                threading.Thread(target=self._accept_front, args=(front,), daemon=True,
                                 name=f'TunnelFront-{name}').start()
            else:
                self._targets[name] = (target_host, target_port)

    def remove(self, name):
        with self._lock:
            front = self._fronts.pop(name, None)
            if front is None and name not in self._targets:
                raise ValueError('Unknown Tunnel mapping')
            self._targets.pop(name, None)
            if front is not None:
                front.active = False
                close_socket(front.listener)
                for sock in tuple(front.streams):
                    close_socket(sock)
                for stream_id, (event, _slot, owner) in tuple(self._waiting.items()):
                    if owner is front:
                        self._waiting.pop(stream_id, None)
                        event.set()
            for stream_id, (sock, owner, event) in tuple(self._target_waiting.items()):
                if owner == name:
                    del self._target_waiting[stream_id]
                    close_socket(sock)
                    event.set()

    def accept(self, sock, packet):
        """Accept already-classified independent TCP socket from the listener."""
        try:
            sock.settimeout(5)
            if not secrets.compare_digest(str(packet.get('token') or ''), self.token):
                raise ValueError('Invalid Tunnel token')
            role = packet.get('role')
            with self._lock:
                if self._closed:
                    raise ConnectionError('Tunnel closed')
                if role == 'control':
                    if self._control is not None:
                        raise ValueError('Duplicate Tunnel control')
                    send_frame(sock, {'ok': True})
                    self._control = sock
                    sock.settimeout(None)
                    threading.Thread(target=self._control_reader, args=(sock,), daemon=True,
                                     name='TunnelPassiveControl').start()
                    return
                if role != 'data':
                    raise ValueError('Unknown Tunnel role')
                stream_id = packet.get('id')
                pending_front = self._waiting.pop(stream_id, None) if isinstance(stream_id, str) else None
                pending_target = self._target_waiting.pop(stream_id, None) if isinstance(stream_id, str) else None
                if pending_front is None and pending_target is None:
                    raise ValueError('Unknown Tunnel stream')
                send_frame(sock, {'ok': True})
                sock.settimeout(None)
                if pending_front is not None:
                    event, slot, _front = pending_front
                    slot.append(sock)
                    event.set()
                else:
                    target, _name, event = pending_target
                    event.set()
                    self._streams.update((sock, target))
                    threading.Thread(target=self._relay_target, args=(sock, target), daemon=True,
                                     name='TunnelPassiveData').start()
                return
        except (OSError, ValueError, TypeError, ConnectionError) as exc:
            self.last_error = str(exc)
        close_socket(sock)

    def _relay_target(self, data, target):
        try:
            bridge(data, target)
        finally:
            with self._lock:
                self._streams.discard(data)
                self._streams.discard(target)

    def _send(self, packet):
        with self._lock:
            control = self._control
        if control is None:
            raise ConnectionError('Tunnel control disconnected')
        send_frame(control, packet, self._send_lock)

    def _control_reader(self, sock):
        try:
            while True:
                packet = recv_frame(sock)
                op, stream_id = packet.get('op'), packet.get('id')
                if op == 'reject':
                    with self._lock:
                        pending = self._waiting.pop(stream_id, None)
                    if pending:
                        pending[0].set()
                elif op == 'open':
                    name = packet.get('name')
                    if not isinstance(stream_id, str) or len(stream_id) != 32:
                        raise ValueError('Invalid Tunnel stream ID')
                    with self._lock:
                        target = self._targets.get(name)
                    if target is None:
                        self._send({'op': 'reject', 'id': stream_id})
                    else:
                        threading.Thread(target=self._open_target, args=(stream_id, name, target),
                                         daemon=True, name='TunnelPassiveTarget').start()
                else:
                    raise ValueError('Unknown Tunnel control message')
        except (OSError, ValueError, ConnectionError) as exc:
            self.last_error = str(exc)
        finally:
            with self._lock:
                if self._control is sock:
                    self._control = None
                for event, _slot, _front in self._waiting.values():
                    event.set()
                for target, _name, event in self._target_waiting.values():
                    close_socket(target)
                    event.set()
                self._target_waiting.clear()
            close_socket(sock)

    def _open_target(self, stream_id, name, address):
        target = None
        event = threading.Event()
        try:
            target = socket.create_connection(address, timeout=8)
            target.settimeout(None)
            with self._lock:
                if self._closed or name not in self._targets or len(self._target_waiting) >= 128:
                    raise ConnectionError('Tunnel target stopped or busy')
                self._target_waiting[stream_id] = (target, name, event)
            self._send({'op': 'ready', 'id': stream_id})
            if event.wait(10):
                return
            # The Active side never registered its data Socket; release target.
            with self._lock:
                if self._target_waiting.pop(stream_id, None) is not None:
                    close_socket(target)
            return
        except (OSError, ValueError, ConnectionError):
            try:
                self._send({'op': 'reject', 'id': stream_id})
            except (OSError, ConnectionError):
                pass
        with self._lock:
            self._target_waiting.pop(stream_id, None)
        close_socket(target)

    def _accept_front(self, front):
        while front.active:
            try:
                sock, _ = front.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_front, args=(front, sock), daemon=True,
                             name='TunnelPassiveFront').start()

    def _handle_front(self, front, sock):
        event, slot = threading.Event(), []
        stream_id = secrets.token_hex(16)
        with self._lock:
            if (not front.active or self._control is None or len(self._waiting) >= 128
                    or len(front.streams) >= 256):
                close_socket(sock)
                return
            front.streams.add(sock)
            self._waiting[stream_id] = (event, slot, front)
        try:
            self._send({'op': 'open', 'id': stream_id, 'name': front.name})
            if not event.wait(10) or not slot:
                return
            with self._lock:
                front.streams.add(slot[0])
            bridge(sock, slot[0])
        except (OSError, ConnectionError):
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

    def close(self):
        with self._lock:
            self._closed = True
            for name in (*tuple(self._fronts), *tuple(self._targets)):
                self.remove(name)
            control, self._control = self._control, None
            for sock in tuple(self._streams):
                close_socket(sock)
            for target, _name, event in self._target_waiting.values():
                close_socket(target)
                event.set()
            self._target_waiting.clear()
        close_socket(control)

    def stream_count(self):
        with self._lock:
            return (sum(len(front.streams) for front in self._fronts.values()) + len(self._streams)) // 2


_runtime = None
_runtime_lock = threading.RLock()


def execute(scope, action, payload):
    """Lazy Control adapter; no import/initialization on ordinary Client startup."""
    from core.protocol.control import TunnelAction
    scope._checkpoint()
    global _runtime
    try:
        name = payload['name']
        with _runtime_lock:
            if action == TunnelAction.START:
                role, token = payload['channel_role'], payload['token']
                if role not in ('passive', 'active'):
                    raise ValueError('Unknown Tunnel channel role')
                if _runtime is not None and (_runtime['role'] != role or _runtime['token'] != token):
                    if not _runtime['endpoint'].empty and _runtime['endpoint'].connected:
                        raise ValueError('Existing Tunnel channel uses another token/role')
                    _close_runtime()
                if _runtime is None:
                    if role == 'passive':
                        from client.connection.bind_listener import current_bind_listener
                        listener = current_bind_listener()
                        if listener is None:
                            raise ValueError('Bind listener is not active')
                        from tunnel.ingress import SharedPortHandler
                        endpoint = PassiveTunnel(token)
                        handler = SharedPortHandler()
                        handler.register(payload['client_id'], endpoint)
                        listener.set_tunnel_handler(handler)
                        _runtime = {'role': role, 'token': token, 'endpoint': endpoint,
                                    'listener': listener, 'handler': handler}
                    else:
                        from client.config.config import RUNTIME_CONFIG
                        from client.connection.transport_connectors import get_connector
                        from core.protocol.rchsocket import RCHSocket
                        from tunnel.server import ActiveTunnel
                        address = (RUNTIME_CONFIG['server_host'], RUNTIME_CONFIG['server_port'])
                        connector = get_connector(RUNTIME_CONFIG.get('server_transport', 'tcp'))
                        connector.validate(RUNTIME_CONFIG)
                        def dial():
                            sock = RCHSocket()
                            try:
                                if not connector.connect(sock, address, RUNTIME_CONFIG):
                                    raise ConnectionError('Tunnel TCP connection failed')
                                return sock.socket
                            except Exception:
                                close_socket(sock.socket)
                                raise
                        endpoint = ActiveTunnel(token, dial, payload['client_id'])
                        _runtime = {'role': role, 'token': token, 'endpoint': endpoint}
                endpoint = _runtime['endpoint']
                try:
                    endpoint.add(name, exposed=payload['expose_on'] == 'client',
                                 **{key: payload[key] for key in ('listen_host', 'listen_port', 'target_host', 'target_port')})
                    if role == 'active' and not endpoint.connected:
                        endpoint.attach()
                except Exception:
                    try:
                        endpoint.remove(name)
                    except ValueError:
                        pass
                    if endpoint.empty:
                        _close_runtime()
                    raise
                result = {'name': name, 'connected': endpoint.connected}
            elif action == TunnelAction.STOP:
                if _runtime is None:
                    raise ValueError('No active Tunnel')
                endpoint = _runtime['endpoint']
                endpoint.remove(name)
                if endpoint.empty:
                    _close_runtime()
                result = {'name': name, 'stopped': True}
            else:
                return 0, 'Unsupported Tunnel action'
        return 1, result
    except (OSError, ValueError, KeyError, TypeError, ConnectionError) as exc:
        with _runtime_lock:
            if _runtime is not None and _runtime['endpoint'].empty:
                _close_runtime()
        return 0, str(exc)


def _close_runtime():
    global _runtime
    state, _runtime = _runtime, None
    if state is None:
        return
    if state['role'] == 'passive':
        state['listener'].set_tunnel_handler(None)
    state['endpoint'].close()
