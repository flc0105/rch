"""Shared RCH listener, detached opt-in Handler, and independent TCP forwarding."""
import concurrent.futures
import http.server
import socket
import struct
import threading
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from client.config.config import RUNTIME_CONFIG
from client.connection.bind_listener import BindListener
from core.protocol.control import ControlDomain
from core.protocol.rchsocket import RCHSocket
from server.persistence.rch_database import RchDatabase
from server.runtime.server_listener import ServerListener
from tunnel import client as client_adapter
from tunnel.ingress import send_hello
from tunnel.instances import TunnelInstanceService, validate_config
from tunnel.transport import recv_frame


CLIENT_ID = '8a91ed62-1f20-480a-9ef8-f98441802b88'


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class HttpTarget(http.server.BaseHTTPRequestHandler):
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

    def log_message(self, *_args):
        pass


@pytest.fixture
def target():
    web = http.server.ThreadingHTTPServer(('127.0.0.1', 0), HttpTarget)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        yield web.server_address[1]
    finally:
        web.shutdown()
        web.server_close()


@pytest.fixture(params=['reverse', 'bind'])
def environment(request, monkeypatch, tmp_path):
    mode = request.param
    port = unused_port()
    client_adapter._runtime = None
    monkeypatch.setitem(RUNTIME_CONFIG, 'connection_mode', mode)
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_host', '127.0.0.1')
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_port', port)
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_transport', 'tcp')
    if mode == 'reverse':
        listener = ServerListener(object(), {'id': 'tcp-default', 'host': '127.0.0.1', 'port': port})
        listener.start()
        listener_manager = SimpleNamespace(running_listener=lambda name: listener if name == 'tcp-default' else None)
        session = SimpleNamespace(listener_id='tcp-default', listener_protocol='tcp',
                                  session_info=SimpleNamespace(client_id=CLIENT_ID))
    else:
        listener = BindListener({'connection_mode': 'bind', 'bind_host': '127.0.0.1', 'bind_port': port})
        listener.start()
        listener._occupied = True  # Main RCH Bind session is already admitted.
        listener_manager = None
        session = SimpleNamespace(bind_dial_endpoint=('127.0.0.1', port),
                                  listener_protocol='bind_tcp',
                                  session_info=SimpleNamespace(client_id=CLIENT_ID))
    server = SimpleNamespace(database=RchDatabase(str(tmp_path / 'tunnel.sqlite')),
                             get_target_connection_by_client_id=lambda _: session,
                             listener_manager=listener_manager)

    class Remote:
        calls = []
        def run_foreground_control(self, conn, domain, action, payload, **kwargs):
            assert conn is session and domain is ControlDomain.TUNNEL
            self.calls.append((action, dict(payload)))
            return client_adapter.execute(SimpleNamespace(_checkpoint=lambda: None), action, payload)

    remote = Remote()
    service = TunnelInstanceService(server)
    try:
        assert listener._tunnel_handler is None
        assert client_adapter._runtime is None
        yield SimpleNamespace(mode=mode, listener=listener, server=server, session=session,
                              remote=remote, service=service, port=port)
    finally:
        if client_adapter._runtime is not None:
            client_adapter._close_runtime()
        for state in tuple(service.runtime._clients):
            # Fixture teardown is deliberately robust to a failed TEST assertion.
            try:
                owned = service.runtime._clients[state]
                service.runtime._close(state, owned)
            except Exception:
                pass
        listener.stop() if mode == 'reverse' else listener.close()
        client_adapter._runtime = None


def mapping(exposure, listen, target_port):
    return dict(expose_on=exposure, listen_host='127.0.0.1', listen_port=listen,
                target_host='127.0.0.1', target_port=target_port)


def test_both_directions_share_original_listener_and_restore_it(environment, target):
    env = environment
    server_port, client_port = unused_port(), unused_port()
    env.service.create(CLIENT_ID, 'server-side', mapping('server', server_port, target))
    env.service.create(CLIENT_ID, 'client-side', mapping('client', client_port, target))
    assert env.listener._tunnel_handler is None  # Saving a definition does not mount a hook.
    assert env.service.start(CLIENT_ID, 'server-side', env.remote)['status'] == 'running'
    handler = env.listener._tunnel_handler
    assert handler is not None
    assert env.service.start(CLIENT_ID, 'client-side', env.remote)['status'] == 'running'
    assert env.listener._tunnel_handler is handler  # One data channel for both directions.
    assert urlopen(f'http://127.0.0.1:{server_port}/server').read() == b'RCH:/server'
    assert urlopen(f'http://127.0.0.1:{client_port}/client').read() == b'RCH:/client'
    calls = len(env.remote.calls)
    for i in range(4):
        assert urlopen(f'http://127.0.0.1:{client_port}/{i}').read() == f'RCH:/{i}'.encode()
    assert len(env.remote.calls) == calls  # Data flow never uses RCH Control.
    assert env.service.stop(CLIENT_ID, 'server-side', env.remote)['status'] == 'stopped'
    assert env.listener._tunnel_handler is handler
    assert urlopen(f'http://127.0.0.1:{client_port}/still').read() == b'RCH:/still'
    assert env.service.stop(CLIENT_ID, 'client-side', env.remote)['status'] == 'stopped'
    assert env.listener._tunnel_handler is None
    assert client_adapter._runtime is None
    assert not env.service.list(CLIENT_ID)['connected']
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', client_port))
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', server_port))


def test_large_binary_and_parallel_streams(environment, target):
    env = environment
    port = unused_port()
    env.service.create(CLIENT_ID, 'file', mapping('client', port, target))
    env.service.start(CLIENT_ID, 'file', env.remote)
    binary = bytes(range(256)) * 32768
    assert urlopen(Request(f'http://127.0.0.1:{port}/upload', data=binary, method='POST'), timeout=20).read() == binary
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda i: urlopen(f'http://127.0.0.1:{port}/{i}', timeout=15).read(), range(20)))
    assert values == [f'RCH:/{i}'.encode() for i in range(20)]
    env.service.stop(CLIENT_ID, 'file', env.remote)


def test_same_host_listen_port_collision_and_failed_start_cleanup(environment, target):
    env = environment
    port = unused_port()
    env.service.create(CLIENT_ID, 'aaa', mapping('server', port, target))
    env.service.create(CLIENT_ID, 'bbb', mapping('client', port, target))
    env.service.start(CLIENT_ID, 'aaa', env.remote)
    with pytest.raises((OSError, RuntimeError), match='Address already in use'):
        env.service.start(CLIENT_ID, 'bbb', env.remote)
    assert env.service.status(CLIENT_ID, 'bbb')['status'] == 'stopped'
    assert urlopen(f'http://127.0.0.1:{port}/aaa').read() == b'RCH:/aaa'
    env.service.stop(CLIENT_ID, 'aaa', env.remote)
    assert env.listener._tunnel_handler is None
    assert env.service.start(CLIENT_ID, 'bbb', env.remote)['status'] == 'running'
    env.service.stop(CLIENT_ID, 'bbb', env.remote)


def test_restart_and_db_persistence_no_autostart(environment, target):
    env = environment
    port = unused_port()
    env.service.create(CLIENT_ID, 'sample', mapping('server', port, target))
    assert env.service.restart(CLIENT_ID, 'sample', env.remote)['status'] == 'running'
    assert urlopen(f'http://127.0.0.1:{port}/before').read() == b'RCH:/before'
    assert env.service.restart(CLIENT_ID, 'sample', env.remote)['status'] == 'running'
    assert urlopen(f'http://127.0.0.1:{port}/after').read() == b'RCH:/after'
    env.service.stop(CLIENT_ID, 'sample', env.remote)
    second_server = SimpleNamespace(database=env.server.database,
                                    get_target_connection_by_client_id=lambda _: env.session,
                                    listener_manager=env.server.listener_manager)
    saved = TunnelInstanceService(second_server)
    assert saved.status(CLIENT_ID, 'sample')['status'] == 'stopped'
    assert saved.remove(CLIENT_ID, 'sample')['deleted']


def test_obsolete_channel_option_rejected_without_compat(environment):
    with pytest.raises(ValueError, match='Unknown tunnel option: channel_port'):
        validate_config({'listen_port': 10000, 'target_port': 8085, 'channel_port': 9444})
    assert 'channel_port' not in validate_config({'listen_port': 10000, 'target_port': 8085})
    assert environment.listener._tunnel_handler is None


def test_bad_token_rejected_without_breaking_existing_channel(environment, target):
    env = environment
    if env.mode != 'reverse':
        pytest.skip('ServerListener handshake routing asserted in reverse mode')
    frontend_port = unused_port()
    env.service.create(CLIENT_ID, 'safe', mapping('server', frontend_port, target))
    env.service.start(CLIENT_ID, 'safe', env.remote)
    with socket.create_connection(('127.0.0.1', env.port), timeout=3) as sock:
        send_hello(sock, client_id=CLIENT_ID, role='control', token='f' * 64)
        sock.settimeout(3)
        with pytest.raises((ConnectionError, OSError)):
            recv_frame(sock)
    assert urlopen(f'http://127.0.0.1:{frontend_port}/good').read() == b'RCH:/good'
    env.service.stop(CLIENT_ID, 'safe', env.remote)


def test_plain_rch_handshake_falls_through_attached_handler(environment, target):
    env = environment
    if env.mode != 'reverse':
        pytest.skip('ServerListener normal inbound greeting case')
    front = unused_port()
    env.service.create(CLIENT_ID, 'sample', mapping('server', front, target))
    env.service.start(CLIENT_ID, 'sample', env.remote)
    called = threading.Event()
    packets = []
    def normal_session(sock, addr, *, initial_handshake=None, **kwargs):
        assert initial_handshake is not None
        packets.append(initial_handshake[0])
        called.set()
        sock.close()
    env.listener.accept_session = normal_session
    with socket.create_connection(('127.0.0.1', env.port), timeout=5) as sock:
        message = b'{"type":"info","id":"ordinary"}'
        sock.sendall(struct.pack(RCHSocket.HEADER_FORMAT, len(message)) + message)
        assert called.wait(2)
    assert packets == [{'type': 'info', 'id': 'ordinary'}]
    env.service.stop(CLIENT_ID, 'sample', env.remote)
    assert env.listener._tunnel_handler is None


def test_bind_normal_session_is_not_tunnel_after_enable_or_disable(environment, target):
    env = environment
    if env.mode != 'bind':
        pytest.skip('Bind-only admission')
    env.listener.release_session()
    # Ordinary new Bind sessions have no first packet; they must remain valid.
    with socket.create_connection(('127.0.0.1', env.port), timeout=3) as sock:
        admitted = env.listener.accept()
        assert admitted is not None
        admitted.close()
    env.listener.release_session()
    front = unused_port()
    env.service.create(CLIENT_ID, 'sample', mapping('client', front, target))
    env.service.start(CLIENT_ID, 'sample', env.remote)
    with socket.create_connection(('127.0.0.1', env.port), timeout=3) as sock:
        admitted = env.listener.accept()
        assert admitted is not None
        admitted.close()
    env.listener.release_session()
    env.service.stop(CLIENT_ID, 'sample', env.remote)
    assert env.listener._tunnel_handler is None


def test_tls_shared_listener_and_pinned_client_socket(tmp_path, target, monkeypatch):
    """Extra Tunnel Sockets honor the same TLS certificate pin as the RCH session."""
    import hashlib
    import shutil
    import ssl
    import subprocess
    if shutil.which('openssl') is None:
        pytest.skip('openssl executable not available for test certificate')
    pem = tmp_path / 'cert.pem'
    key = tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-days', '1', '-subj', '/CN=localhost', '-keyout', str(key),
                    '-out', str(pem)], check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(pem), str(key))
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.read_text())).hexdigest()
    port = unused_port()
    listener = ServerListener(object(), {'host': '127.0.0.1', 'port': port,
                                         'id': 'tls-test', 'protocol': 'tls_tcp'}, ssl_context=context)
    listener.start()
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_host', '127.0.0.1')
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_port', port)
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_transport', 'tls_tcp')
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_tls_fingerprint', fingerprint)
    client_adapter._runtime = None
    session = SimpleNamespace(listener_id='tls-test', listener_protocol='tls_tcp',
                              session_info=SimpleNamespace(client_id=CLIENT_ID))
    manager = SimpleNamespace(running_listener=lambda name: listener)
    server = SimpleNamespace(database=RchDatabase(str(tmp_path / 'tls.sqlite')),
                             get_target_connection_by_client_id=lambda _: session,
                             listener_manager=manager)
    service = TunnelInstanceService(server)

    class Remote:
        def run_foreground_control(self, conn, domain, action, payload, **kwargs):
            return client_adapter.execute(SimpleNamespace(_checkpoint=lambda: None), action, payload)

    try:
        front = unused_port()
        service.create(CLIENT_ID, 'secure', mapping('client', front, target))
        assert service.start(CLIENT_ID, 'secure', Remote())['status'] == 'running'
        assert urlopen(f'http://127.0.0.1:{front}/tls').read() == b'RCH:/tls'
        service.stop(CLIENT_ID, 'secure', Remote())
        assert listener._tunnel_handler is None
        monkeypatch.setitem(RUNTIME_CONFIG, 'server_tls_fingerprint', '0' * 64)
        with pytest.raises(RuntimeError, match='certificate fingerprint mismatch'):
            service.start(CLIENT_ID, 'secure', Remote())
        assert listener._tunnel_handler is None
        assert service.status(CLIENT_ID, 'secure')['status'] == 'stopped'
        assert client_adapter._runtime is None
    finally:
        if client_adapter._runtime:
            client_adapter._close_runtime()
        for state in tuple(service.runtime._clients):
            service.runtime._close(state, service.runtime._clients[state])
        listener.stop()


def test_half_close_propagates_in_both_directions(environment):
    env = environment
    target_port = unused_port()
    target_sock = socket.socket()
    target_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    target_sock.bind(('127.0.0.1', target_port))
    target_sock.listen(8)
    target_sock.settimeout(0.3)
    stopped = threading.Event()
    def serve():
        while not stopped.is_set():
            try:
                conn, _ = target_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            def respond(sock):
                with sock:
                    chunks = []
                    while True:
                        chunk = sock.recv(32768)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    sock.sendall(b'received:' + b''.join(chunks))
            threading.Thread(target=respond, args=(conn,), daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()
    try:
        for side in ('server', 'client'):
            front = unused_port()
            name = f'half-{side}'
            env.service.create(CLIENT_ID, name, mapping(side, front, target_port))
            env.service.start(CLIENT_ID, name, env.remote)
            with socket.create_connection(('127.0.0.1', front), timeout=5) as conn:
                conn.settimeout(10)
                conn.sendall(b'abc' * 30000)
                conn.shutdown(socket.SHUT_WR)
                output = bytearray()
                while True:
                    part = conn.recv(65536)
                    if not part:
                        break
                    output.extend(part)
                assert output == b'received:' + b'abc' * 30000
            env.service.stop(CLIENT_ID, name, env.remote)
    finally:
        stopped.set()
        target_sock.close()
