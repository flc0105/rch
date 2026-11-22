"""Loopback Bind TCP A-stage tests using real TCP, without Web/UI dependencies."""
import json
import socket
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.connection.bind_listener import BindListener
from client.connection.lifecycle import ClientConnectionLifecycle
from client.connection.receiver_worker import ClientReceiverWorker
from client.config.feature_config import resolve_features
from server.connection.connection_manager import ConnectionManager
from server.runtime.bind_connector import BindConnector


def _available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _config(port):
    return {
        'connection_mode': 'bind', 'bind_host': '127.0.0.1',
        'bind_port': port,
    }


def _wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


@pytest.mark.parametrize('override', [
    {'bind_host': ''},
    {'bind_port': 0},
    {'bind_port': True},
    {'connection_mode': 'reverse'},
])
def test_bind_listener_validates_config(override):
    with pytest.raises(ValueError):
        BindListener({**_config(9443), **override})


def test_bind_socket_occupancy_pause_resume_and_port_conflict():
    port = _available_port()
    listener = BindListener(_config(port))
    listener.start()
    try:
        with pytest.raises(OSError):
            duplicate = BindListener(_config(port))
            duplicate.start()
        outgoing = socket.create_connection(('127.0.0.1', port), timeout=2)
        accepted = listener.accept()
        assert accepted.getpeername()[0] == '127.0.0.1'
        second = socket.create_connection(('127.0.0.1', port), timeout=2)
        assert _wait_for(lambda: second.recv(1) == b'', timeout=1)
        second.close()
        listener.set_accepting(False)
        accepted.close()
        outgoing.close()
        listener.release_session()
        paused = socket.create_connection(('127.0.0.1', port), timeout=2)
        paused.settimeout(1)
        assert paused.recv(1) == b''
        paused.close()
        listener.set_accepting(True)
        outgoing2 = socket.create_connection(('127.0.0.1', port), timeout=2)
        accepted2 = listener.accept()
        assert accepted2.getpeername()[0] == '127.0.0.1'
        accepted2.close()
        outgoing2.close()
        listener.release_session()
    finally:
        listener.close()


class _Session:
    def __init__(self, transport, info):
        self.transport = transport
        self.session_info = SimpleNamespace(client_id=info['id'])
        self.address = transport.address
        self.context = SimpleNamespace(transport_failure=None, client_session_token_service=None, server_disconnect_request=None)
        self.runtime = SimpleNamespace(pending_results=SimpleNamespace(close=lambda: None))
        self.received = []

    def note_server_disconnect(self, command=''):
        self.context.server_disconnect_request = {'at': time.monotonic(), 'command': command}

    def recv_message(self):
        self.received.append(self.transport.recv())

    def close(self):
        self.transport.socket.close()


class _Api:
    def __init__(self):
        self.registered = []
        self.closed = []

    def create_web_connection(self, transport, addr, info):
        return _Session(transport, info)

    def handle_connection_registered(self, session):
        self.registered.append(session)

    def handle_connection_closed(self, session):
        self.closed.append(session)


@pytest.fixture
def bind_server(tmp_path):
    api = _Api()
    server = SimpleNamespace(connections=ConnectionManager(),
                             web_service=SimpleNamespace(connection_api=api))
    port = _available_port()
    return server, BindConnector(server), port, api


def _connect_info(port, client_id=None):
    listener = BindListener(_config(port))
    listener.start()
    connected = []
    client_id = client_id or str(uuid.uuid4())

    def serve_once():
        sock = listener.accept()
        from core.protocol.rchsocket import RCHSocket
        client_socket = RCHSocket()
        client_socket.socket.close()
        client_socket.socket = sock
        client_socket.send({'id': client_id, 'type': 'info', 'hostname': 'local-bind-test'})
        connected.append(client_socket)

    thread = threading.Thread(target=serve_once, daemon=True)
    thread.start()
    return listener, connected, thread


def test_bind_outbound_dial_uses_existing_info_registration_and_can_reconnect(bind_server):
    server, connector, port, api = bind_server
    listener, accepted, thread = _connect_info(port)
    try:
        session = connector.connect('127.0.0.1', port)
        assert _wait_for(lambda: bool(accepted))
        assert session.session_info.client_id == api.registered[0].session_info.client_id
        assert session in server.connections
        assert connector.connect('127.0.0.1', port) is session
        client_id = session.session_info.client_id
        assert connector.disconnect(client_id) == client_id
        assert session.context.server_disconnect_request['command'] == 'disconnect'
        assert _wait_for(lambda: session not in server.connections)
        listener.release_session()
        accepted[0].close()
        # One Client process, same client ID; a new session is registered.
        second = []
        def send_again():
            from core.protocol.rchsocket import RCHSocket
            sock = listener.accept()
            conn = RCHSocket()
            conn.socket.close()
            conn.socket = sock
            conn.send({'type': 'info', 'id': client_id})
            second.append(conn)
        t = threading.Thread(target=send_again, daemon=True)
        t.start()
        next_session = connector.connect('127.0.0.1', port)
        assert next_session is not session
        assert next_session.session_info.client_id == client_id
        connector.disconnect(client_id)
        assert _wait_for(lambda: next_session not in server.connections)
        if second:
            second[0].close()
    finally:
        listener.close()


def test_bind_invalid_handshake_does_not_register(bind_server):
    server, connector, port, api = bind_server
    listener = BindListener(_config(port))
    listener.start()
    try:
        def invalid():
            from core.protocol.rchsocket import RCHSocket
            sock = listener.accept()
            conn = RCHSocket()
            conn.socket.close()
            conn.socket = sock
            conn.send({'type': 'info', 'id': 'not-a-uuid'})
            conn.close()
        t = threading.Thread(target=invalid, daemon=True)
        t.start()
        with pytest.raises(ValueError, match='Invalid Client ID'):
            connector.connect('127.0.0.1', port)
        assert server.connections.all() == []
        assert api.registered == []
    finally:
        listener.close()


def test_bind_refuses_client_id_takeover(bind_server):
    server, connector, port, api = bind_server
    client_id = str(uuid.uuid4())
    prior = SimpleNamespace(session_info=SimpleNamespace(client_id=client_id))
    server.connections.add(prior)
    listener, accepted, thread = _connect_info(port, client_id=client_id)
    try:
        with pytest.raises(ValueError, match='already has an active session'):
            connector.connect('127.0.0.1', port)
        assert server.connections.get_by_client_id(client_id) is prior
        assert not api.registered
    finally:
        listener.close()
        for socket_obj in accepted:
            socket_obj.close()


@pytest.mark.parametrize('host,port', [('', 9443), ('a b', 9443), ('127.0.0.1', True), ('127.0.0.1', 0)])
def test_bind_endpoint_validation(bind_server, host, port):
    _server, connector, _port, _api = bind_server
    with pytest.raises(ValueError):
        connector.connect(host, port)

def test_bind_mode_is_opt_in_and_reverse_path_untouched(monkeypatch):
    from client.connection import lifecycle
    fake = SimpleNamespace()
    fake.server = SimpleNamespace(adopt_socket=lambda sock: None)
    fake.RECONNECT_INTERVAL = 0.01
    worker = ClientReceiverWorker()
    fake.receiver_worker = worker
    fake.client_id = str(uuid.uuid4())
    fake.features = resolve_features('linux', overrides={'watchdog': False, 'pty': False})
    fake.watchdog_manager = None
    fake.process_recovery_watchdog_manager = None
    mode = _config(_available_port())
    monkeypatch.setattr(lifecycle, 'RUNTIME_CONFIG', mode)
    manager = ClientConnectionLifecycle(fake)
    monkeypatch.setattr(lifecycle, 'BindListener', BindListener, raising=False)
    # The normal Client's connection factory is independent of mode; only
    # connect_socket selects the Bind listener.
    assert manager._bind_listener is None
    assert manager.is_paused is False
    assert manager.create_connection().client_id == fake.client_id


def test_real_client_execution_over_bind_socket_and_session_reconnect(monkeypatch, bind_server):
    """Use actual Client runtime, receiver, getpid command and heartbeat frames."""
    import queue
    from client.connection import lifecycle as client_lifecycle
    from client.connection.server_connection import ServerConnection
    server, connector, port, api = bind_server
    fake = SimpleNamespace(
        client_id=str(uuid.uuid4()), features=resolve_features('linux', overrides={
            'watchdog': False, 'pty': False, 'screen_view': False, 'clipboard': False,
        }),
        watchdog_manager=None, process_recovery_watchdog_manager=None,
        receiver_worker=ClientReceiverWorker(), recovery_source='', info=None,
    )
    fake.server = ServerConnection(features=fake.features)
    fake.server.client_id = fake.client_id
    fake.connection_lifecycle = ClientConnectionLifecycle(fake)
    monkeypatch.setattr(client_lifecycle, 'RUNTIME_CONFIG', _config(port))
    monkeypatch.setattr(client_lifecycle, 'ClientInfoBuilder', lambda **kwargs: SimpleNamespace(
        build=lambda: {'type': 'info', 'id': fake.client_id, 'hostname': 'test', 'cwd': '.'},
    ))
    stopped = threading.Event()
    errors = []

    def client_loop():
        try:
            while not stopped.is_set():
                try:
                    fake.connection_lifecycle.connect_socket()
                    fake.connection_lifecycle.handshake()
                    fake.receiver_worker.start(fake.server)
                    while not stopped.is_set():
                        error = fake.receiver_worker.pop_error()
                        if error is not None:
                            raise error
                        try:
                            result = fake.server.recv_command(timeout=0.05)
                        except queue.Empty:
                            continue
                        if result:
                            fake.server.send_result(*result)
                except OSError:
                    if not stopped.is_set():
                        fake.connection_lifecycle.reset_connection()
                except Exception as exc:
                    if not stopped.is_set():
                        errors.append(exc)
                    break
        finally:
            fake.connection_lifecycle.close_current_connection()
            fake.connection_lifecycle.close_bind_listener()

    thread = threading.Thread(target=client_loop, daemon=True)
    thread.start()
    try:
        assert _wait_for(lambda: fake.connection_lifecycle._bind_listener is not None
                         and fake.connection_lifecycle._bind_listener._socket is not None)
        first = connector.connect('127.0.0.1', port)
        first.transport.send({'type': 'heartbeat', 'id': 100, 'ts': 'now'})
        assert _wait_for(lambda: any(item.get('type') == 'heartbeat_ack' for item in first.received))
        first.transport.send({'type': 'command', 'id': 101, 'text': 'getpid'})
        assert _wait_for(lambda: any(item.get('type') == 'result' and item.get('id') == 101
                                     for item in first.received), timeout=5)
        assert not errors, repr(errors)
        assert connector.disconnect(fake.client_id) == fake.client_id
        assert _wait_for(lambda: first not in server.connections)
        assert _wait_for(lambda: fake.connection_lifecycle._bind_listener is not None
                         and not fake.connection_lifecycle._bind_listener._occupied)
        second = connector.connect('127.0.0.1', port)
        assert second is not first
        assert second.session_info.client_id == fake.client_id
        second.transport.send({'type': 'command', 'id': 102, 'text': 'getpid'})
        assert _wait_for(lambda: any(item.get('type') == 'result' and item.get('id') == 102
                                     for item in second.received), timeout=5)
        assert not errors, repr(errors)
        connector.disconnect(fake.client_id)
    finally:
        stopped.set()
        fake.connection_lifecycle.close_current_connection()
        fake.connection_lifecycle.close_bind_listener()
        thread.join(timeout=3)
    assert not errors, repr(errors)


def test_reverse_connection_cannot_replace_an_active_exclusive_session():
    manager = ConnectionManager()
    current = SimpleNamespace(session_info=SimpleNamespace(client_id='existing'),
                              exclusive_registration=True)
    manager.add(current)
    replacement = SimpleNamespace(session_info=SimpleNamespace(client_id='existing'))
    with pytest.raises(ValueError, match='does not allow replacement'):
        manager.add(replacement)
    assert manager.get_by_client_id('existing') is current


def test_bind_listener_accepts_lan_host_configuration():
    listener = BindListener({**_config(9443), 'bind_host': '0.0.0.0'})
    assert listener.address == ('0.0.0.0', 9443)

def test_concurrent_dial_of_same_target_is_rejected(bind_server):
    _server, connector, port, _api = bind_server
    listener = BindListener(_config(port))
    listener.start()
    errors = []

    def stalled_dial():
        try:
            connector.connect('127.0.0.1', port)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=stalled_dial, daemon=True)
    thread.start()
    try:
        assert _wait_for(lambda: ('127.0.0.1', port) in connector._inflight)
        with pytest.raises(RuntimeError, match='already in progress'):
            connector.connect('127.0.0.1', port)
        accepted = listener.accept()
        accepted.close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert errors
        assert not connector._inflight
    finally:
        listener.close()


def test_bind_loss_releases_old_socket_before_reverse_backoff(monkeypatch):
    from unittest.mock import Mock
    from client.app.client import Client
    from client.app import client as client_app
    fake = SimpleNamespace(
        RECONNECT_INTERVAL=15,
        connection_lifecycle=SimpleNamespace(
            is_paused=False, is_bind_mode=True,
            reset_connection=Mock(),
        ),
        connect=Mock(),
    )
    monkeypatch.setattr(client_app.time, 'sleep', Mock(side_effect=AssertionError('unexpected sleep')))
    Client._recover_from_connection_error(fake, OSError('closed'))
    fake.connection_lifecycle.reset_connection.assert_called_once_with()
    fake.connect.assert_called_once_with()


def test_client_wait_survives_bind_initial_handshake_error_and_toolbar_disconnect(monkeypatch, bind_server):
    """Exercise the real Client wait/recovery path, not a substitute receive loop."""
    from types import MethodType
    from client.app.client import Client
    from client.connection import lifecycle as client_lifecycle
    from client.connection.server_connection import ServerConnection

    server, connector, port, _api = bind_server
    features = resolve_features('linux', overrides={
        'watchdog': False, 'pty': False, 'screen_view': False, 'clipboard': False,
    })
    client = SimpleNamespace(
        client_id=str(uuid.uuid4()), features=features, watchdog_manager=None,
        process_recovery_watchdog_manager=None,
        receiver_worker=ClientReceiverWorker(), recovery_source='', info=None,
        RECONNECT_INTERVAL=0.01, local_ipc=None,
    )
    client.server = ServerConnection(features=features)
    client.server.client_id = client.client_id
    client.connection_lifecycle = ClientConnectionLifecycle(client)
    monkeypatch.setattr(client_lifecycle, 'RUNTIME_CONFIG', _config(port))
    monkeypatch.setattr(client_lifecycle, 'ClientInfoBuilder', lambda **kwargs: SimpleNamespace(
        build=lambda: {'type': 'info', 'id': client.client_id, 'hostname': 'test', 'cwd': '.'},
    ))
    client._recover_from_connection_error = MethodType(Client._recover_from_connection_error, client)
    client._wait_for_commands = MethodType(Client._wait_for_commands, client)
    original_connect = MethodType(Client.connect, client)
    startup_calls = []

    def connect():
        startup_calls.append(True)
        if len(startup_calls) == 1:
            raise OSError('simulated initial handshake loss')
        return original_connect()

    client.connect = connect
    stop = threading.Event()
    actual_recv_command = ServerConnection.recv_command

    def recv_command(connection, timeout=None):
        if stop.is_set():
            raise SystemExit()
        return actual_recv_command(connection, timeout=timeout)

    monkeypatch.setattr(ServerConnection, 'recv_command', recv_command)
    errors = []

    def run_client():
        try:
            Client.connect_initial(client)
            Client.wait(client)
        except BaseException as exc:
            errors.append(exc)
        finally:
            client.connection_lifecycle.close_current_connection()
            client.connection_lifecycle.close_bind_listener()

    thread = threading.Thread(target=run_client, daemon=True)
    thread.start()
    try:
        assert _wait_for(lambda: client.connection_lifecycle._bind_listener is not None
                         and client.connection_lifecycle._bind_listener._socket is not None)
        first = connector.connect('127.0.0.1', port)
        assert first.session_info.client_id == client.client_id
        assert len(startup_calls) >= 2
        assert connector.disconnect(client.client_id) == client.client_id
        assert _wait_for(lambda: first not in server.connections)
        assert thread.is_alive(), repr(errors)
        assert client.connection_lifecycle._bind_listener._socket.getsockname()[1] == port
        # Reconnect immediately, before Client's receive loop necessarily
        # releases its old session. The Server's bounded retry bridges that gap.
        second = connector.connect('127.0.0.1', port)
        assert second.session_info.client_id == client.client_id
        assert second is not first
        stop.set()
        assert _wait_for(lambda: not thread.is_alive(), timeout=5)
        assert not errors, repr(errors)
    finally:
        stop.set()
        client.connection_lifecycle.close_current_connection()
        client.connection_lifecycle.close_bind_listener()
        thread.join(timeout=3)
