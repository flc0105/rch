"""Server-owned Tunnel channel lifecycle and detachable shared-port hooks.

The first mapping mounts a handler on the existing RCH listener; the last
mapping unmounts it. No Tunnel work runs in ordinary RCH handshakes when idle.
"""
import secrets
import socket
import threading

from tunnel.client import PassiveTunnel
from tunnel.ingress import SharedPortHandler
from tunnel.server import ActiveTunnel


class ServerChannels:
    def __init__(self, server):
        self.server = server
        self._lock = threading.RLock()
        self._clients = {}

    @staticmethod
    def _control_payload(client_id, name, config, token, role):
        return {'client_id': client_id, 'name': name, 'channel_role': role,
                'token': token, **config}

    @staticmethod
    def _local_mapping(endpoint, role, name, config):
        endpoint.add(name, exposed=(config['expose_on'] == 'server'),
                     **{key: config[key] for key in (
                         'listen_host', 'listen_port', 'target_host', 'target_port')})

    def _create(self, client_id, conn):
        token = secrets.token_hex(32)
        # This is the actual endpoint of the established session, not a guess
        # based on public/private IPs or the requested exposure direction.
        endpoint_address = getattr(conn, 'bind_dial_endpoint', None)
        if endpoint_address is not None:
            def dial():
                sock = socket.create_connection(endpoint_address, timeout=8)
                if getattr(conn, 'bind_transport', 'tcp') == 'mtls_tcp':
                    try:
                        sock = self.server.listener_manager.identities.wrap_outbound_socket(sock)
                    except Exception:
                        sock.close()
                        raise
                return sock
            endpoint = ActiveTunnel(token, dial, client_id)
            return {'role': 'active', 'token': token, 'endpoint': endpoint, 'mappings': {}}

        listener_id = getattr(conn, 'listener_id', '')
        manager = getattr(self.server, 'listener_manager', None)
        listener = manager.running_listener(listener_id) if manager is not None else None
        if listener is None:
            raise ValueError('Original RCH listening endpoint is unavailable')
        if listener.protocol not in ('tcp', 'mtls_tcp'):
            raise ValueError('Tunnel requires an RCH TCP listener')
        endpoint = PassiveTunnel(token)
        handler = listener._tunnel_handler
        if handler is None:
            handler = SharedPortHandler()
        handler.register(client_id, endpoint)
        listener.set_tunnel_handler(handler)
        return {'role': 'passive', 'token': token, 'endpoint': endpoint,
                'listener': listener, 'handler': handler, 'mappings': {}}

    def start(self, client_id, conn, name, config, control):
        with self._lock:
            state = self._clients.get(client_id)
            first = state is None
            if first:
                state = self._create(client_id, conn)
                self._clients[client_id] = state
            endpoint = state['endpoint']
            if name in state['mappings']:
                raise ValueError('Tunnel already running')
            remote_started = False
            try:
                self._local_mapping(endpoint, state['role'], name, config)
                remote_role = 'passive' if state['role'] == 'active' else 'active'
                control('start', self._control_payload(client_id, name, config, state['token'], remote_role))
                remote_started = True
                if state['role'] == 'active' and not endpoint.connected:
                    endpoint.attach()
                if not endpoint.connected:
                    raise ConnectionError('Independent Tunnel TCP control connection did not connect')
                state['mappings'][name] = dict(config)
            except Exception:
                if remote_started:
                    try:
                        control('stop', {'name': name})
                    except Exception:
                        pass
                try:
                    endpoint.remove(name)
                except ValueError:
                    pass
                if first and endpoint.empty:
                    self._close(client_id, state)
                raise

    def _close(self, client_id, state):
        self._clients.pop(client_id, None)
        if state['role'] == 'passive':
            listener, handler = state['listener'], state['handler']
            handler.unregister(client_id, state['endpoint'])
            if handler.empty and listener._tunnel_handler is handler:
                listener.set_tunnel_handler(None)
        state['endpoint'].close()

    def stop(self, client_id, name, control):
        with self._lock:
            state = self._clients.get(client_id)
            if state is None or name not in state['mappings']:
                raise ValueError('No running Tunnel mapping')
            control('stop', {'name': name})
            state['endpoint'].remove(name)
            del state['mappings'][name]
            if not state['mappings']:
                self._close(client_id, state)

    def list(self, client_id):
        with self._lock:
            state = self._clients.get(client_id)
            if state is None:
                return {'connected': False, 'mappings': [], 'streams': 0, 'last_error': ''}
            endpoint = state['endpoint']
            return {'connected': endpoint.connected,
                    'mappings': [dict(name=name, **config) for name, config in state['mappings'].items()],
                    'streams': endpoint.stream_count(), 'last_error': endpoint.last_error}


def manager_for(server):
    if not hasattr(server, '_tunnel_channels'):
        server._tunnel_channels = ServerChannels(server)
    return server._tunnel_channels
