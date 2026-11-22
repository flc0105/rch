"""Socket-level validation for the optional in-process Bind TCP forwarder."""
import http.server
import socket
import threading
import time
import urllib.request

import pytest

from tunnel.client import ClientTunnel
from tunnel.server import ServerTunnels
from tunnel.transport import close_socket


def free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class ApiHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def do_GET(self):
        body = ('RCH:' + self.path).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def target():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ApiHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def tunnels():
    client = ClientTunnel()
    server = ServerTunnels()
    created = []
    def start(name, target_port, *, listen_port=None, channel_port=None):
        channel_port = channel_port or free_port()
        listen_port = listen_port or free_port()
        peer, first = server.prepare('client-A', '127.0.0.1', channel_port, name)
        client.start(name=name, listen_host='127.0.0.1', listen_port=listen_port,
                     channel_port=channel_port, token=peer.token)
        server.ready('client-A', peer, name, '127.0.0.1', target_port,
                     '127.0.0.1', listen_port, first=first)
        created.append(name)
        return listen_port, channel_port
    try:
        yield start, client, server
    finally:
        for name in reversed(created):
            try:
                client.stop(name)
                server.stopped('client-A', name)
            except ValueError:
                pass


def test_http_get_post_large_file_and_repeated_connections(target, tunnels):
    start, client, server = tunnels
    front, _ = start('rch-web', target)
    assert urllib.request.urlopen(f'http://127.0.0.1:{front}/jobs?a=1').read() == b'RCH:/jobs?a=1'
    body = bytes(range(256)) * 32768  # 8 MiB, unmodified through the tunnel
    req = urllib.request.Request(f'http://127.0.0.1:{front}/upload', data=body, method='POST')
    assert urllib.request.urlopen(req, timeout=15).read() == body
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(lambda i: urllib.request.urlopen(
            f'http://127.0.0.1:{front}/n/{i}', timeout=10).read(), range(20)))
    assert replies == [f'RCH:/n/{i}'.encode() for i in range(20)]
    assert server.list('client-A')['connected'] is True


def test_second_mapping_stop_and_listener_reuse(target, tunnels):
    start, client, server = tunnels
    one, channel = start('web-a', target)
    two, _ = start('web-b', target, channel_port=channel)
    assert urllib.request.urlopen(f'http://127.0.0.1:{two}/second').read() == b'RCH:/second'
    assert len(server.list('client-A')['mappings']) == 2
    client.stop('web-a')
    server.stopped('client-A', 'web-a')
    assert len(server.list('client-A')['mappings']) == 1
    assert urllib.request.urlopen(f'http://127.0.0.1:{two}/still-live').read() == b'RCH:/still-live'
    client.stop('web-b')
    server.stopped('client-A', 'web-b')
    assert server.list('client-A')['connected'] is False
    probe = socket.socket()
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # TCP port has actually been released, not just hidden from `list`.
        probe.bind(('127.0.0.1', two))
    finally:
        probe.close()


def test_reject_bad_token_and_no_remote_target(tunnels):
    start, client, server = tunnels
    unused_target = free_port()
    front, ingress = start('unreachable', unused_target)
    with socket.create_connection(('127.0.0.1', ingress), timeout=2) as bad:
        from tunnel.transport import send_frame, recv_frame
        send_frame(bad, {'role': 'data', 'token': '0' * 64, 'id': '1' * 32})
        with pytest.raises((ConnectionError, OSError)):
            recv_frame(bad)
    req = urllib.request.Request(f'http://127.0.0.1:{front}/unavailable')
    with pytest.raises(Exception):
        urllib.request.urlopen(req, timeout=5).read()
    assert server.list('client-A')['connected']


def test_persistent_tunnel_not_dependent_on_rch_session(target, tunnels):
    start, _, server = tunnels
    front, _ = start('survives', target)
    # The manager holds no RCH ClientSession instance or main RCH socket.
    for _ in range(2):
        assert urllib.request.urlopen(f'http://127.0.0.1:{front}/after-rch-disconnect').read() == b'RCH:/after-rch-disconnect'
    assert server.list('client-A')['mappings'][0]['name'] == 'survives'


def test_cli_spec_is_registered():
    from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
    for args in (
        'start --name test-web --listen-host 127.0.0.1 --listen-port 18085 --target-port 8085',
        'stop --name test-web', 'list', 'status --name test-web',
    ):
        invocation = SERVER_COMMAND_REGISTRY.parse_invocation('tunnel', args)
        assert invocation.command == 'tunnel'


def test_raw_tcp_half_close_stream(target, tunnels):
    """Protocol is opaque: a binary service can wait for client FIN then reply."""
    receiver = socket.socket()
    receiver.bind(('127.0.0.1', 0))
    receiver.listen(1)
    receiver.settimeout(5)
    destination = receiver.getsockname()[1]
    received = []

    def serve():
        sock, _ = receiver.accept()
        with sock:
            chunks = []
            while True:
                chunk = sock.recv(32768)
                if not chunk:
                    break
                chunks.append(chunk)
            received.append(b''.join(chunks))
            sock.sendall(b'OK:' + received[0][:8])
        receiver.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    start, _, _ = tunnels
    front, _ = start('binary', destination)
    payload = bytes(range(256)) * 2048
    with socket.create_connection(('127.0.0.1', front), timeout=5) as sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        answer = b''
        while True:
            part = sock.recv(512)
            if not part:
                break
            answer += part
    t.join(timeout=5)
    assert answer == b'OK:' + payload[:8]
    assert received == [payload]


def test_builtin_start_status_second_mapping_and_stop(target, monkeypatch):
    import types
    from tunnel import client as client_module
    from core.protocol.control import TunnelAction
    from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
    from server.application.command.tunnel_builtin_support import TunnelBuiltinSupport
    from client.config.config import RUNTIME_CONFIG
    from core.protocol.message_queue import ResultChunk

    local = ClientTunnel()
    monkeypatch.setattr(client_module, '_manager', local)
    monkeypatch.setitem(RUNTIME_CONFIG, 'connection_mode', 'bind')
    server = types.SimpleNamespace()
    session = types.SimpleNamespace(
        listener_protocol='bind_tcp', bind_dial_endpoint=('127.0.0.1', 9443),
        session_info=types.SimpleNamespace(client_id='test-client'),
    )
    class Remote:
        def stream_command(self, conn, text, *, domain, action, payload, **kwargs):
            assert conn is session and domain == 'tunnel'
            result = client_module.execute(types.SimpleNamespace(_checkpoint=lambda: None), action, payload)
            yield ResultChunk(result[0], result[1], True)

    def invoke(text):
        item = SERVER_COMMAND_REGISTRY.parse_invocation('tunnel', text)
        return TunnelBuiltinSupport(server, session, Remote(), lambda: '').execute(item)

    a, b, channel = free_port(), free_port(), free_port()
    try:
        status, msg = invoke(f'start --name app --listen-port {a} --target-port {target} --channel-port {channel}')
        assert status == 1, msg
        assert urllib.request.urlopen(f'http://127.0.0.1:{a}/api').read() == b'RCH:/api'
        status, msg = invoke(f'start --name other --listen-port {b} --target-port {target} --channel-port {channel}')
        assert status == 1, msg
        status, msg = invoke('list')
        assert status == 1 and 'app' in msg and 'other' in msg
        # Server-owned tunnel survives a new RCH session with the same Client ID.
        old_session = session
        session = types.SimpleNamespace(listener_protocol='bind_tcp',
                                        bind_dial_endpoint=('127.0.0.1', 9443),
                                        session_info=types.SimpleNamespace(client_id='test-client'))
        assert invoke('status --name app')[0] == 1
        assert invoke('stop --name app')[0] == 1
        assert urllib.request.urlopen(f'http://127.0.0.1:{b}/other').read() == b'RCH:/other'
        assert invoke('stop --all')[0] == 1
        assert invoke('list')[0] == 1
        assert server._tcp_tunnels.list('test-client')['mappings'] == []
    finally:
        for name in ('app', 'other'):
            try:
                local.stop(name)
            except ValueError:
                pass
        if hasattr(server, '_tcp_tunnels'):
            peer = server._tcp_tunnels.peer('test-client')
            if peer:
                peer.close()


def test_new_server_process_can_reclaim_orphan_tunnel(target):
    client = ClientTunnel()
    first = ServerTunnels()
    channel = free_port()
    old_front = free_port()
    new_front = free_port()
    peer, initial = first.prepare('bind-a', '127.0.0.1', channel, 'old-service')
    client.start(name='old-service', listen_host='127.0.0.1', listen_port=old_front,
                 channel_port=channel, token=peer.token)
    first.ready('bind-a', peer, 'old-service', '127.0.0.1', target,
                '127.0.0.1', old_front, first=initial)
    assert urllib.request.urlopen(f'http://127.0.0.1:{old_front}/old').read() == b'RCH:/old'
    peer.close()  # simulates the old Server process exiting
    for _ in range(100):
        with client._lock:
            if client._control is None:
                break
        time.sleep(0.01)
    second = ServerTunnels()
    peer2, initial2 = second.prepare('bind-a', '127.0.0.1', channel, 'new-service')
    client.start(name='new-service', listen_host='127.0.0.1', listen_port=new_front,
                 channel_port=channel, token=peer2.token)
    second.ready('bind-a', peer2, 'new-service', '127.0.0.1', target,
                 '127.0.0.1', new_front, first=initial2)
    try:
        assert urllib.request.urlopen(f'http://127.0.0.1:{new_front}/new').read() == b'RCH:/new'
        assert 'old-service' not in client._fronts
    finally:
        client.stop('new-service')
        second.stopped('bind-a', 'new-service')
