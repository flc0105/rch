"""Active Tunnel channel: independent outbound TCP sockets to the RCH listener.

Which process owns this side depends only on which end actually dialled the
successful RCH session, never on where the forwarded port is exposed.
"""
import secrets
import socket
import threading

from tunnel.client import _Front
from tunnel.ingress import send_hello
from tunnel.transport import bridge, close_socket, listen, recv_frame, send_frame


class ActiveTunnel:
    def __init__(self, token, dial, client_id):
        if not isinstance(token, str) or len(token) != 64:
            raise ValueError('Invalid Tunnel token')
        self.token = token
        self._dial = dial
        self.client_id = client_id
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._control = None
        self._fronts = {}
        self._targets = {}
        self._waiting = {}
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

    def _connect(self, role, stream_id=None):
        sock = self._dial()
        try:
            sock.settimeout(8)
            send_hello(sock, client_id=self.client_id, role=role, token=self.token, stream_id=stream_id)
            if recv_frame(sock).get('ok') is not True:
                raise ConnectionError('Tunnel registration rejected')
            sock.settimeout(None)
            return sock
        except Exception:
            close_socket(sock)
            raise

    def attach(self):
        sock = self._connect('control')
        with self._lock:
            if self._closed:
                close_socket(sock)
                raise ConnectionError('Tunnel stopped')
            if self._control is not None:
                close_socket(sock)
                return
            self._control = sock
        threading.Thread(target=self._control_reader, args=(sock,), daemon=True,
                         name='TunnelActiveControl').start()

    def add(self, name, *, exposed, listen_host, listen_port, target_host, target_port):
        with self._lock:
            if self._closed or name in self._fronts or name in self._targets:
                raise ValueError('Duplicate or closed Tunnel mapping')
            if exposed:
                front = _Front(name, listen(listen_host, listen_port))
                self._fronts[name] = front
                threading.Thread(target=self._accept_front, args=(front,), daemon=True,
                                 name=f'TunnelActiveFront-{name}').start()
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

    def _send(self, packet):
        with self._lock:
            sock = self._control
        if sock is None:
            raise ConnectionError('Tunnel control disconnected')
        send_frame(sock, packet, self._send_lock)

    def _control_reader(self, sock):
        try:
            while True:
                packet = recv_frame(sock)
                op, stream_id = packet.get('op'), packet.get('id')
                if op in ('ready', 'reject'):
                    with self._lock:
                        pending = self._waiting.get(stream_id)
                    if pending:
                        pending[1].append(op == 'ready')
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
                                         daemon=True, name='TunnelActiveTarget').start()
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
            close_socket(sock)

    def _open_target(self, stream_id, name, address):
        target = data = None
        try:
            target = socket.create_connection(address, timeout=8)
            data = self._connect('data', stream_id)
            with self._lock:
                if self._closed or name not in self._targets:
                    return
                self._streams.update((target, data))
            target.settimeout(None)
            bridge(target, data)
        except (OSError, ValueError, ConnectionError) as exc:
            self.last_error = str(exc)
            try:
                self._send({'op': 'reject', 'id': stream_id})
            except (OSError, ConnectionError):
                pass
        finally:
            with self._lock:
                self._streams.discard(target)
                self._streams.discard(data)
            close_socket(target)
            close_socket(data)

    def _accept_front(self, front):
        while front.active:
            try:
                sock, _ = front.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_front, args=(front, sock), daemon=True,
                             name='TunnelActiveStream').start()

    def _handle_front(self, front, sock):
        stream_id = secrets.token_hex(16)
        event, ready = threading.Event(), []
        data = None
        with self._lock:
            if (not front.active or self._control is None or len(self._waiting) >= 128
                    or len(front.streams) >= 256):
                close_socket(sock)
                return
            front.streams.add(sock)
            self._waiting[stream_id] = (event, ready, front)
        try:
            self._send({'op': 'open', 'id': stream_id, 'name': front.name})
            if not event.wait(10) or not ready or not ready[0]:
                return
            data = self._connect('data', stream_id)
            with self._lock:
                if not front.active:
                    return
                front.streams.add(data)
            bridge(sock, data)
        except (OSError, ValueError, ConnectionError) as exc:
            self.last_error = str(exc)
        finally:
            with self._lock:
                self._waiting.pop(stream_id, None)
                front.streams.discard(sock)
                if data is not None:
                    front.streams.discard(data)
            close_socket(sock)
            close_socket(data)

    def stream_count(self):
        with self._lock:
            return (sum(len(front.streams) for front in self._fronts.values()) + len(self._streams)) // 2

    def close(self):
        with self._lock:
            self._closed = True
            for name in (*tuple(self._fronts), *tuple(self._targets)):
                self.remove(name)
            control, self._control = self._control, None
            for sock in tuple(self._streams):
                close_socket(sock)
        close_socket(control)
