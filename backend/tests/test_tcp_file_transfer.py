"""Managed file streams over actual TCP sockets, without a second ClientSession."""
import hashlib
import os
import socket
import sqlite3
import ssl
import subprocess
import threading
import time
import zipfile
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from client.config import runtime_config
from client.config.config import RUNTIME_CONFIG
from client.connection.bind_listener import BindListener
from client.connection.transport_connectors import get_connector
from client.transfers.manager import ClientTransferManager
from core.protocol.auxiliary import close_socket, send_greeting
from core.protocol.file_stream import DATA_GREETING, receive_control, require_ok, send_control
from core.protocol.rchsocket import RCHSocket
from core.transfer_settings import FileTransferMode
from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.application.auth.client_session_token_service import ClientSessionTokenService
from server.application.transfers import tcp_transport as server_transport
from server.application.transfers.transfer_service import TransferService
from server.application.web.transfer_api import WebTransferApi
from server.persistence.rch_database import RchDatabase
from server.runtime.server_listener import ServerListener
from server.connection.runtime.pending_results import PendingResults
from server.application.transfers.inline_registration import register_inline_transfer
from client.runtime.execution.scope import ExecutionScope
from client.runtime.execution.context import ExecutionContext
from unittest.mock import Mock
from pathlib import Path
from tunnel.ingress import SharedPortHandler


class CatalogArtifacts:
    """Exercise the production SQLite catalog without requiring the Web stack."""
    def __init__(self, db, root):
        self.root = root
        self.catalog = ArtifactSqliteCatalog(db, root)

    def allocate_artifact_path(self, artifact_type, machine_id, original_name):
        artifact_id = uuid.uuid4().hex
        path = self.root / self.catalog.object_relative_path(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        return {'artifact_id': artifact_id, 'file_path': str(path), 'machine_id': machine_id}

    def register_existing_artifact(self, *, artifact_type, category, hostname, machine_id,
                                   original_name, file_path, artifact_id, client_id, addr, extra, source_command_id=None):
        return self.catalog.save({'artifact_id': artifact_id, 'artifact_type': artifact_type,
                                  'machine_id': machine_id, 'original_name': original_name,
                                  'saved_path': file_path, 'size': os.path.getsize(file_path),
                                  'saved_at': datetime.now().isoformat(), 'client_id': client_id,
                                  'extra': extra, 'source_command_id': source_command_id, **({'category': category} if artifact_type == 'saved' else {})})

    def get_artifact_by_id(self, artifact_id):
        return self.catalog.get(artifact_id)

    def get_artifact_file_path(self, artifact_id):
        return self.catalog.physical_path(self.catalog.get(artifact_id)['saved_path'])

    def delete_artifact(self, artifact_id):
        os.unlink(self.get_artifact_file_path(artifact_id))
        self.catalog.delete(artifact_id)


class Events:
    def __init__(self):
        self.items = []

    def publish(self, kind, payload, **kwargs):
        self.items.append((kind, dict(payload)))


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_until(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'Condition timed out'
        time.sleep(0.01)


@pytest.fixture(params=['bind', 'reverse', 'tls', 'bind-tunnel', 'reverse-tunnel'])
def environment(request, monkeypatch, tmp_path):
    mode = request.param
    is_bind = mode.startswith('bind')
    proto = 'bind_tcp' if is_bind else 'tls_tcp' if mode == 'tls' else 'tcp'
    events = Events()
    db = RchDatabase(str(tmp_path / 'rch.db'))
    artifacts = CatalogArtifacts(db, tmp_path / 'web' / 'artifacts')
    tokens = ClientSessionTokenService()
    transfers = TransferService(events, db)
    tcp = server_transport.TcpTransferTransport(transfers, artifacts, tokens, events)
    transfers.tcp_transport = tcp
    server = SimpleNamespace(web_service=SimpleNamespace(transfer_api=SimpleNamespace(transfer_service=transfers)))
    session = SimpleNamespace(session_info=SimpleNamespace(client_id='client-1', machine_id='machine-1',
                                                           hostname='localhost', addr='127.0.0.1'),
                              listener_id='test', listener_protocol=proto, context=SimpleNamespace())
    token = tokens.issue(session)
    session.context.client_session_token = token
    client = RCHSocket()
    client.client_session_token = token
    client.client_id = 'client-1'
    listener_port = port()
    accepted = threading.Event()
    main_received = []
    server_main = RCHSocket()
    server_main.socket.close()
    monkeypatch.setattr(runtime_config, 'FILE_TRANSFER_MODE', FileTransferMode.TCP_STREAMING.value)
    monkeypatch.setitem(RUNTIME_CONFIG, 'server_transport', 'tcp' if is_bind else proto)
    if is_bind:
        listener = BindListener({'connection_mode': 'bind', 'bind_host': '127.0.0.1', 'bind_port': listener_port})
        listener.start()
        session.bind_dial_endpoint = ('127.0.0.1', listener_port)
        server_main.socket = socket.create_connection(session.bind_dial_endpoint, timeout=5)
        client.socket.close()
        client.socket = listener.accept()
        client.bind_listener = listener
    else:
        ctx = None
        if mode == 'tls':
            import shutil
            if not shutil.which('openssl'):
                pytest.skip('OpenSSL is required for the TLS test')
            cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)],
                           check=True, capture_output=True)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert), str(key))
            fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
            monkeypatch.setitem(RUNTIME_CONFIG, 'server_tls_fingerprint', fingerprint)
        listener = ServerListener(server, {'host': '127.0.0.1', 'port': listener_port,
                                           'id': 'test', 'protocol': proto}, ssl_context=ctx)

        def register_main(sock, addr, *, initial_handshake, **kwargs):
            assert initial_handshake[0]['type'] == 'info'
            server_main.socket = sock
            accepted.set()
            return session

        listener.accept_session = register_main
        listener.start()
        connector = get_connector(proto)
        assert connector.connect(client, ('127.0.0.1', listener_port), RUNTIME_CONFIG)
        client.send({'type': 'info', 'id': 'client-1'})
        assert accepted.wait(5)
    if mode.endswith('tunnel'):
        listener.set_tunnel_handler(SharedPortHandler())
    server_main.socket.settimeout(None)
    manager = ClientTransferManager(client)
    session.runtime = SimpleNamespace(pending_results=PendingResults())
    session.get_foreground_task = lambda: {}
    session.send = server_main.send
    client.runtime = SimpleNamespace(transfer_manager=manager)
    client.send_event = lambda command_id, event: client.send({"type": "result", "id": command_id, "event": event})

    def handle_updates():
        try:
            while True:
                data = server_main.recv()
                if data['type'] == 'transfer_update':
                    transfers.handle_client_update('client-1', data, session=session)
                elif data['type'] == 'transfer_register':
                    register_inline_transfer(transfers, artifacts, session, data)
                else:
                    main_received.append(data)
        except OSError:
            pass
        finally:
            db.close_thread_connection()

    receiver = threading.Thread(target=handle_updates, daemon=True)
    receiver.start()
    def handle_client():
        try:
            while True:
                data = client.recv()
                if data["type"] == "transfer_register":
                    manager.handle_registration(data)
                elif data["type"] == "transfer_cancel":
                    manager.cancel_transfer(data["transfer_id"])
        except OSError:
            pass
    client_receiver = threading.Thread(target=handle_client, daemon=True)
    client_receiver.start()
    env = SimpleNamespace(transfers=transfers, artifacts=artifacts, events=events, manager=manager,
                          session=session, client=client, tcp=tcp, main_received=main_received,
                          listener=listener, token=token, mode=mode, port=listener_port)
    try:
        yield env
    finally:
        manager.cancel_all()
        tcp.close_session(session)
        close_socket(client.socket)
        close_socket(server_main.socket)
        receiver.join(3)
        client_receiver.join(3)
        if is_bind:
            listener.close()
        else:
            listener.stop()
        db.close_thread_connection()


def create(env, direction, filename, *, source='', total=None):
    return env.transfers.create_transfer(client_id='client-1', direction=direction, filename=filename,
                                         source_path=str(source), total_bytes=total,
                                         metadata={'transport': 'client_transfer_manager'})['transfer_id']


def terminal(env, transfer_id, state):
    result = env.transfers.wait_for_terminal(transfer_id, timeout=10)
    assert result['state'] == state, result
    wait_until(lambda: transfer_id not in env.manager._tasks)
    return result


@pytest.mark.parametrize('size', [0, 2 * 1024 * 1024 + 31])
def test_upload_download_and_artifact(environment, tmp_path, size):
    env = environment
    source = tmp_path / 'source.bin'
    source.write_bytes(os.urandom(size))
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    result = terminal(env, transfer, 'completed')
    artifact = env.artifacts.get_artifact_by_id(result['artifact_id'])
    assert artifact['client_id'] == 'client-1'
    assert artifact['machine_id'] == 'machine-1'
    assert artifact['size'] == size
    assert open(env.artifacts.get_artifact_file_path(result['artifact_id']), 'rb').read() == source.read_bytes()
    assert result['metadata']['file_transfer_mode'] == 'tcp_streaming'
    assert any(kind == 'artifact_created' for kind, _ in env.events.items)

    target = tmp_path / 'destination'
    transfer = create(env, 'server_to_client', source.name, source=source, total=size)
    env.manager.start_transfer(transfer, 'server_to_client_file', {'filename': source.name, 'save_dir': str(target)})
    result = terminal(env, transfer, 'completed')
    assert (target / source.name).read_bytes() == source.read_bytes()
    assert result['destination_path'] == str(target / source.name)
    assert not list(target.glob('.rch-upload-*'))


def test_zip_and_preview_paths(environment, tmp_path):
    env = environment
    source = tmp_path / 'document.txt'
    source.write_text('hello', encoding='utf-8')
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_preview', {'path': str(source)})
    result = terminal(env, transfer, 'completed')
    assert env.artifacts.get_artifact_by_id(result['artifact_id'])['artifact_type'] == 'preview'
    transfer = create(env, 'client_to_server', 'archive.zip')
    env.manager.start_transfer(transfer, 'client_to_server_zip', {'paths': [str(source)], 'archive_name': 'archive.zip'})
    result = terminal(env, transfer, 'completed')
    archive = env.artifacts.get_artifact_file_path(result['artifact_id'])
    with zipfile.ZipFile(archive) as z:
        assert z.read(source.name) == b'hello'
    transfer = create(env, 'client_to_server', source.name)
    # Client path must have a ZIP suffix, unlike the Artifact object-store path.
    zip_source = tmp_path / 'entry-source.zip'
    zip_source.write_bytes(open(archive, 'rb').read())
    env.manager.start_transfer(transfer, 'client_to_server_zip_entry', {'path': str(zip_source), 'entry_name': source.name})
    result = terminal(env, transfer, 'completed')
    assert open(env.artifacts.get_artifact_file_path(result['artifact_id']), 'rb').read() == b'hello'


def test_cancel_blocked_data_keeps_main_socket_alive(environment, tmp_path, monkeypatch):
    env = environment
    source = tmp_path / 'blocked.bin'
    with source.open('wb') as f:
        f.truncate(16 * 1024 * 1024)
    entered, release = threading.Event(), threading.Event()
    original = server_transport.receive_file

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(server_transport, 'receive_file', blocked)
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    try:
        assert entered.wait(5)
        env.client.send({'type': 'main_probe', 'id': 1})
        wait_until(lambda: env.main_received == [{'type': 'main_probe', 'id': 1}])
        env.transfers.mark_cancelling(transfer)
        assert env.manager.cancel_transfer(transfer)['accepted']
        terminal(env, transfer, 'cancelled')
    finally:
        release.set()
    wait_until(lambda: not env.tcp._active)
    assert not list(tmp_path.rglob('.rch-transfer-*'))
    assert not any(kind == 'artifact_created' for kind, _ in env.events.items)


def test_download_conflict_and_cancel(environment, tmp_path, monkeypatch):
    env = environment
    source = tmp_path / 'new.bin'
    source.write_bytes(b'new contents')
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'file.bin').write_bytes(b'old contents')
    transfer = create(env, 'server_to_client', 'file.bin', source=source, total=source.stat().st_size)
    env.manager.start_transfer(transfer, 'server_to_client_file', {'filename': 'file.bin', 'save_dir': str(target), 'conflict_policy': 'stop'})
    terminal(env, transfer, 'failed')
    assert (target / 'file.bin').read_bytes() == b'old contents'
    transfer = create(env, 'server_to_client', 'file.bin', source=source, total=source.stat().st_size)
    env.manager.start_transfer(transfer, 'server_to_client_file', {'filename': 'file.bin', 'save_dir': str(target), 'conflict_policy': 'replace'})
    terminal(env, transfer, 'completed')
    assert (target / 'file.bin').read_bytes() == b'new contents'

    entered, release = threading.Event(), threading.Event()
    original = server_transport.send_file

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(server_transport, 'send_file', blocked)
    transfer = create(env, 'server_to_client', 'cancel.bin', source=source, total=source.stat().st_size)
    env.manager.start_transfer(transfer, 'server_to_client_file', {'filename': 'cancel.bin', 'save_dir': str(target)})
    try:
        assert entered.wait(5)
        env.transfers.mark_cancelling(transfer)
        assert env.manager.cancel_transfer(transfer)['accepted']
        terminal(env, transfer, 'cancelled')
    finally:
        release.set()
    wait_until(lambda: not env.tcp._active)
    assert not (target / 'cancel.bin').exists()
    assert not list(target.glob('.rch-upload-*'))


def test_tcp_mode_only_applies_to_managed_transfers(monkeypatch):
    from client.runtime.http_transfer.http_file_transfer_service import HttpFileTransferService
    monkeypatch.setattr(runtime_config, 'FILE_TRANSFER_MODE', 'tcp_streaming')
    assert HttpFileTransferService(object()).get_transfer_strategy().get_mode_name() == 'http_streaming'
    monkeypatch.setattr(runtime_config, 'FILE_TRANSFER_MODE', 'http_simple')
    service = HttpFileTransferService(object(), transfer_mode='http_simple')
    monkeypatch.setattr(runtime_config, 'FILE_TRANSFER_MODE', 'http_streaming')
    assert service.get_transfer_strategy().get_mode_name() == 'http_simple'
    assert HttpFileTransferService(object()).get_transfer_strategy().get_mode_name() == 'http_streaming'


def test_checksum_failure_leaves_no_artifact(environment, tmp_path, monkeypatch):
    from client.transfers import tcp_transport as client_transport
    env = environment
    source = tmp_path / 'bad.bin'
    source.write_bytes(b'integrity check')
    def bad_digest(sock, path, *, metadata, **kwargs):
        content = open(path, 'rb').read()
        send_control(sock, {'size': len(content), **metadata})
        sock.sendall(content)
        send_control(sock, {'sha256': '0' * 64})
        return len(content)
    monkeypatch.setattr(client_transport, 'send_file', bad_digest)
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    result = terminal(env, transfer, 'failed')
    assert not result['artifact_id']
    wait_until(lambda: not env.tcp._active)
    assert not list(tmp_path.rglob('.rch-transfer-*'))
    assert not any(kind == 'artifact_created' for kind, _ in env.events.items)


def test_two_concurrent_file_connections(environment, tmp_path):
    env = environment
    sources = [tmp_path / f'concurrent-{i}.bin' for i in range(2)]
    for source in sources:
        source.write_bytes(os.urandom(1024 * 1024 + 17))
    ids = [create(env, 'client_to_server', source.name) for source in sources]
    for transfer, source in zip(ids, sources):
        env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    for transfer, source in zip(ids, sources):
        result = terminal(env, transfer, 'completed')
        assert open(env.artifacts.get_artifact_file_path(result['artifact_id']), 'rb').read() == source.read_bytes()


@pytest.mark.parametrize('direction', ['client_to_server', 'server_to_client'])
def test_cancel_waits_for_client_context(environment, tmp_path, monkeypatch, direction):
    env = environment
    source = tmp_path / 'delayed-cancel.bin'
    with source.open('wb') as f:
        f.truncate(16 * 1024 * 1024)
    target = tmp_path / 'destination'
    entered, resume, checked, finish = (threading.Event() for _ in range(4))
    method = 'receive_file' if direction == 'client_to_server' else 'send_file'
    original = getattr(server_transport, method)

    def paused(*args, **kwargs):
        entered.set()
        assert resume.wait(5)
        kwargs['checkpoint']()
        checked.set()
        assert finish.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(server_transport, method, paused)
    transfer = create(env, direction, source.name, source=source, total=source.stat().st_size)
    if direction == 'client_to_server':
        env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    else:
        env.manager.start_transfer(transfer, 'server_to_client_file', {'filename': source.name, 'save_dir': str(target)})
    pending = []
    api = WebTransferApi(env.transfers, SimpleNamespace(
        get_target_connection_by_client_id=lambda _: SimpleNamespace(send=pending.append)))
    try:
        assert entered.wait(5)
        assert api.cancel_transfer(transfer)['stage'] == 'cancelling'
        assert len(pending) == 1
        resume.set()
        # In v66 this checkpoint closes the data socket before the queued Cancel arrives.
        assert checked.wait(3)
        assert env.transfers.get_transfer(transfer)['state'] == 'running'
        assert env.manager.cancel_transfer(pending[0]['transfer_id'])['accepted']
        result = terminal(env, transfer, 'cancelled')
        assert not result['error'] and not result['artifact_id']
    finally:
        resume.set()
        finish.set()
    wait_until(lambda: not env.tcp._active)
    assert not (target / source.name).exists()
    assert not list(tmp_path.rglob('.rch-transfer-*'))
    assert not list(tmp_path.rglob('.rch-upload-*'))
    assert not any(kind == 'artifact_created' for kind, _ in env.events.items)
    assert not any(kind == 'file_transfer_lifecycle' and data.get('lifecycle') == 'error'
                   for kind, data in env.events.items)


def test_repeated_cancel_during_client_commit(environment, tmp_path, monkeypatch):
    from client.runtime.filesystem import conflict_policy
    env = environment
    source = tmp_path / 'payload.bin'
    source.write_bytes(b'complete contents')
    target = tmp_path / 'destination'
    entered, release = threading.Event(), threading.Event()
    original = conflict_policy.prepare_upload_file_commit

    def prepare(*args, **kwargs):
        commit = original(*args, **kwargs)
        def paused(path):
            entered.set()
            assert release.wait(5)
            return commit(path)
        return paused

    monkeypatch.setattr(conflict_policy, 'prepare_upload_file_commit', prepare)
    transfer = create(env, 'server_to_client', source.name, source=source, total=source.stat().st_size)
    env.transfers.update_transfer(transfer, metadata={'source': 'remote_file_upload', 'browser_stage': False})
    env.manager.start_transfer(transfer, 'server_to_client_file', {'filename': source.name, 'save_dir': str(target)})
    replies = []
    api = WebTransferApi(env.transfers, SimpleNamespace(get_target_connection_by_client_id=lambda _: SimpleNamespace(
        send=lambda message: replies.append(env.manager.cancel_transfer(message['transfer_id'])))))
    try:
        assert entered.wait(5)
        assert api.cancel_transfer(transfer)['stage'] == 'cancelling'
        repeated = api.cancel_transfer(transfer)
        assert repeated['state'] == 'running' and repeated['stage'] == 'cancelling'
        assert len(replies) == 2 and all(not reply['accepted'] for reply in replies)
    finally:
        release.set()
    result = terminal(env, transfer, 'completed')
    assert not result['error']
    assert (target / source.name).read_bytes() == source.read_bytes()
    assert env.transfers.history.get(transfer)['state'] == 'completed'


def test_cancel_before_server_artifact_commit(environment, tmp_path, monkeypatch):
    env = environment
    source = tmp_path / 'last-chunk.bin'
    source.write_bytes(b'complete contents')
    entered, release = threading.Event(), threading.Event()
    original = env.transfers.commit_tcp_artifact

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(env.transfers, 'commit_tcp_artifact', paused)
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    pending = []
    api = WebTransferApi(env.transfers, SimpleNamespace(
        get_target_connection_by_client_id=lambda _: SimpleNamespace(send=pending.append)))
    try:
        assert entered.wait(5)
        assert api.cancel_transfer(transfer)['stage'] == 'cancelling'
        assert len(pending) == 1
    finally:
        release.set()
    result = terminal(env, transfer, 'cancelled')
    wait_until(lambda: not env.tcp._active)
    assert not result['error'] and not result['artifact_id']
    assert not env.artifacts.catalog.list()
    assert not list(p for p in env.artifacts.root.rglob('*') if p.is_file())


def test_history_failure_rolls_back_new_artifact(environment, tmp_path, monkeypatch):
    env = environment
    source = tmp_path / 'commit.bin'
    source.write_bytes(b'new artifact contents')
    # Preserve an unrelated existing Artifact during compensation.
    previous = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(previous, 'client_to_server_file', {'path': str(source)})
    existing = terminal(env, previous, 'completed')['artifact_id']
    wait_until(lambda: not env.tcp._active)
    original = env.transfers.history.record_terminal
    registered = []

    def fail(item):
        if item['state'] == 'completed':
            registered.append(item['artifact_id'])
            assert env.artifacts.get_artifact_by_id(item['artifact_id'])
            raise sqlite3.OperationalError('injected terminal history failure')
        return original(item)

    monkeypatch.setattr(env.transfers.history, 'record_terminal', fail)
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    result = terminal(env, transfer, 'failed')
    wait_until(lambda: not env.tcp._active)
    assert len(registered) == 1 and not result['artifact_id']
    assert not env.artifacts.get_artifact_by_id(registered[0])
    assert not (env.artifacts.root / env.artifacts.catalog.object_relative_path(registered[0])).exists()
    assert env.artifacts.get_artifact_by_id(existing)
    assert open(env.artifacts.get_artifact_file_path(existing), 'rb').read() == source.read_bytes()
    assert not list(tmp_path.rglob('.rch-transfer-*'))
    assert not any(kind == 'artifact_created' and data.get('artifact_id') == registered[0]
                   for kind, data in env.events.items)


def test_unrequested_data_disconnect_is_failure(environment, tmp_path, monkeypatch):
    env = environment
    source = tmp_path / 'disconnected.bin'
    with source.open('wb') as f:
        f.truncate(16 * 1024 * 1024)
    entered, release = threading.Event(), threading.Event()
    original = server_transport.receive_file

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(server_transport, 'receive_file', paused)
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    try:
        assert entered.wait(5)
        env.tcp.close_session(env.session)
        result = terminal(env, transfer, 'failed')
        assert result['error'] and not result['artifact_id']
    finally:
        release.set()
    wait_until(lambda: not env.tcp._active)
    assert not list(tmp_path.rglob('.rch-transfer-*'))
    assert not env.artifacts.catalog.list()


def test_cancel_terminal_can_follow_closed_data_socket(environment, tmp_path, monkeypatch):
    env = environment
    source = tmp_path / 'slow-terminal.bin'
    with source.open('wb') as f:
        f.truncate(16 * 1024 * 1024)
    entered, release, terminal_arrived, deliver, waiting = (threading.Event() for _ in range(5))
    original_receive = server_transport.receive_file
    original_update = env.transfers.handle_client_update
    original_wait = env.transfers.wait_for_terminal
    timeouts = []

    def paused_receive(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original_receive(*args, **kwargs)

    def paused_update(client_id, payload, **kwargs):
        if payload.get('state') == 'cancelled':
            terminal_arrived.set()
            assert deliver.wait(8)
        return original_update(client_id, payload, **kwargs)

    def tracked_wait(transfer_id, timeout=None):
        if threading.current_thread().name == 'TcpFileTransfer':
            timeouts.append(timeout)
            waiting.set()
        return original_wait(transfer_id, timeout=timeout)

    monkeypatch.setattr(server_transport, 'receive_file', paused_receive)
    monkeypatch.setattr(env.transfers, 'handle_client_update', paused_update)
    monkeypatch.setattr(env.transfers, 'wait_for_terminal', tracked_wait)
    transfer = create(env, 'client_to_server', source.name)
    env.manager.start_transfer(transfer, 'client_to_server_file', {'path': str(source)})
    try:
        assert entered.wait(5)
        env.transfers.mark_cancelling(transfer)
        assert env.manager.cancel_transfer(transfer)['accepted']
        assert terminal_arrived.wait(5)
        release.set()
        assert waiting.wait(5)
        assert timeouts == [server_transport.IO_TIMEOUT]
        assert env.transfers.get_transfer(transfer)['state'] == 'running'
    finally:
        release.set()
        deliver.set()
    assert not terminal(env, transfer, 'cancelled')['error']
    wait_until(lambda: not env.tcp._active)
    assert not list(tmp_path.rglob('.rch-transfer-*'))


def inline_owner(env, request_type='acmd', **request):
    command_id = 123
    env.session.runtime.pending_results.register(command_id, request={
        'type': request_type, 'id': command_id, 'extra': {'tab_id': 'inline-tab'}, **request})
    return ExecutionScope(env.client, ExecutionContext(command_id=command_id))


def assert_inline_artifact(env, expected):
    def history():
        return env.transfers.list_transfers()['recent']
    wait_until(lambda: bool(history()))
    item = env.transfers.get_transfer(history()[0]['transfer_id'])
    assert item['state'] == 'completed', item
    assert item['metadata']['file_transfer_mode'] == 'tcp_streaming'
    assert item['metadata']['source_command_id'] == 123
    artifact = env.artifacts.get_artifact_by_id(item['artifact_id'])
    assert Path(env.artifacts.get_artifact_file_path(item['artifact_id'])).read_bytes() == expected
    assert str(artifact['source_command_id']) == '123'
    return artifact


def test_inline_download(environment, tmp_path):
    from client.commands.acmd.common.files import download
    env = environment
    owner = inline_owner(env)
    source = tmp_path / 'source.bin'
    source.write_bytes(b'inline-download')
    assert download(owner, {'path': str(source), 'name': 'renamed.bin'}) == (1, '')
    assert assert_inline_artifact(env, b'inline-download')['original_name'] == 'renamed.bin'
    assert not env.manager._tasks


def test_inline_clipboard_staged_file(environment, tmp_path):
    from client.clipboard.manager import ClipboardManager
    from core.protocol.control import ClipboardAction, ControlDomain
    env = environment
    source = tmp_path / 'source.bin'
    source.write_bytes(b'clipboard-file')
    url = '/api/upload-tmp/staged-id/file.bin'
    payload = {'kind': 'files', 'items': [{'type': 'directory', 'path': 'group'},
               {'type': 'file', 'path': 'group/file.bin', 'name': 'file.bin', 'url': url}], 'roots': ['group']}
    owner = inline_owner(env, 'control', domain=ControlDomain.CLIPBOARD, action=ClipboardAction.SET, payload=payload)
    env.artifacts.get_upload_temp_file_path = lambda temp_id, name: str(source)
    clipboard = ClipboardManager.__new__(ClipboardManager)
    clipboard._operation_lock = threading.RLock()
    clipboard.staging_dir = str(tmp_path / 'clipboard')
    clipboard.adapter = Mock()
    clipboard._os_alias = 'linux'
    clipboard._macos_console_identity = None
    status, result = clipboard.execute(owner, ClipboardAction.SET, payload)
    assert status == 1, result
    paths = clipboard.adapter.set_files.call_args.args[0]
    assert len(paths) == 1 and (Path(paths[0]) / 'file.bin').read_bytes() == b'clipboard-file'
    wait_until(lambda: bool(env.transfers.list_transfers()['recent']))
    item = env.transfers.get_transfer(env.transfers.list_transfers()['recent'][0]['transfer_id'])
    assert item['state'] == 'completed', item
    assert item['metadata']['file_transfer_mode'] == 'tcp_streaming'
    assert not env.manager._tasks


def test_inline_clipboard_image(environment, tmp_path):
    from client.clipboard.manager import ClipboardManager
    from core.protocol.control import ClipboardAction, ControlDomain
    from PIL import Image
    from io import BytesIO
    env = environment
    image = BytesIO()
    Image.new('RGB', (2, 2), 'blue').save(image, format='PNG')
    owner = inline_owner(env, 'control', domain=ControlDomain.CLIPBOARD, action=ClipboardAction.GET, payload={})
    clipboard = ClipboardManager.__new__(ClipboardManager)
    clipboard._operation_lock = threading.RLock()
    clipboard.adapter = Mock()
    clipboard.adapter.get_snapshot.return_value = {'kind': 'image', 'data': image.getvalue(), 'format': 'png'}
    status, result = clipboard.execute(owner, ClipboardAction.GET, {})
    assert status == 1, result
    artifact = assert_inline_artifact(env, image.getvalue())
    assert result['data']['artifact']['artifact_id'] == artifact['artifact_id']


def test_inline_clipboard_reject_unstaged(environment, tmp_path):
    from core.protocol.control import ClipboardAction, ControlDomain
    env = environment
    owner = inline_owner(env, 'control', domain=ControlDomain.CLIPBOARD, action=ClipboardAction.SET,
                         payload={'items': [{'url': '/api/upload-tmp/allowed/file.bin'}]})
    env.artifacts.get_upload_temp_file_path = Mock(side_effect=AssertionError('must not access unlisted file'))
    with pytest.raises(RuntimeError, match='not staged'):
        with env.manager.inline_transfer(owner, direction='server_to_client', filename='file.bin',
                                         source_url='/api/upload-tmp/unlisted/file.bin'):
            pytest.fail('unexpected registration success')
    assert not env.manager._tasks
    env.artifacts.get_upload_temp_file_path.assert_not_called()
    assert not env.transfers.list_transfers()['items']


@pytest.mark.parametrize('mode', ['http_simple', 'http_streaming'])
def test_inline_http_modes(environment, tmp_path, monkeypatch, mode):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from email.parser import BytesParser
    from email.policy import default
    from client.http.client_api import ClientApiClient
    from client.commands.acmd.common.files import download
    import json
    env = environment
    data = b'local HTTP inline test\0' * 100
    uploads = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            msg = BytesParser(policy=default).parsebytes(b'Content-Type: '+self.headers['Content-Type'].encode()+b'\r\n\r\n'+raw)
            uploads.append(next(part.get_payload(decode=True) for part in msg.iter_parts() if part.get_param('name', header='Content-Disposition') == 'file'))
            body = json.dumps({'code':0, 'data':{'artifact_id':'test-http-artifact','original_name':'test.bin'}}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(runtime_config, 'FILE_TRANSFER_MODE', mode)
        owner = inline_owner(env)
        owner._client_api = ClientApiClient(base_url=f'http://127.0.0.1:{server.server_port}')
        source = tmp_path/'test.bin'
        source.write_bytes(data)
        assert download(owner, {'path':str(source), 'name':''}) == (1, '')
        assert uploads == [data]
        wait_until(lambda: bool(env.transfers.list_transfers()['recent']))
        item = env.transfers.get_transfer(env.transfers.list_transfers()['recent'][0]['transfer_id'])
        assert item['state'] == 'completed', item
        assert item['metadata']['file_transfer_mode'] == mode
        assert item['artifact_id'] == 'test-http-artifact'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.parametrize('command', ['screenshot', 'webcam_snap'])
def test_inline_media_command(environment, monkeypatch, command):
    # Capture is isolated from the real desktop; bytes are synthetic test data.
    import importlib
    env = environment
    owner = inline_owner(env, 'command')
    if command == 'screenshot':
        module = importlib.import_module('client.commands.shell.standalone.screenshot')
        owner.command_platform = 'win'
        monkeypatch.setattr(module, '_capture_win', lambda _owner, path: Path(path).write_bytes(b'test-media'))
    else:
        module = importlib.import_module('client.commands.shell.platform.mac')
        def run(args, **kwargs):
            if args[0] == 'imagesnap':
                Path(args[-1]).write_bytes(b'test-media')
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(module.subprocess, 'run', run)
    assert getattr(module, command)(owner)[0] == 1
    assert_inline_artifact(env, b'test-media')


def test_inline_cancel_from_transfer_center(environment, tmp_path, monkeypatch):
    from client.transfers import tcp_transport as client_transport
    from client.commands.acmd.common.files import download
    from client.runtime.execution.context import CommandCancelledError
    env = environment
    source = tmp_path/'source.bin'
    source.write_bytes(b'inline cancel')
    owner = inline_owner(env)
    entered, release = threading.Event(), threading.Event()
    original = client_transport.send_file
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(client_transport, 'send_file', paused)
    errors = []
    def run():
        try:
            download(owner, {'path':str(source), 'name':''})
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(5)
        item = env.transfers.list_transfers(tab_id='inline-tab')['active'][0]
        assert not env.transfers.list_transfers(tab_id='other-tab')['active']
        api = WebTransferApi(env.transfers, SimpleNamespace(get_target_connection_by_client_id=lambda _:env.session))
        api.cancel_transfer(item['transfer_id'], tab_id='inline-tab')
        wait_until(owner.execution_context.is_cancel_requested)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], CommandCancelledError), errors
    terminal(env, item['transfer_id'], 'cancelled')
    assert not list(env.artifacts.root.rglob('*.*'))


def test_inline_artifact_send_to_clipboard(environment, tmp_path):
    from client.clipboard.manager import ClipboardManager
    from core.protocol.control import ClipboardAction, ControlDomain
    from server.application.web.clipboard_api import WebClipboardApi
    env = environment
    shared = tmp_path / 'shared.bin'
    shared.write_bytes(b'shared artifact')
    staged = tmp_path / 'staged.bin'
    url = '/api/upload-tmp/staged-id/staged.bin'
    clipboard = ClipboardManager.__new__(ClipboardManager)
    clipboard._operation_lock = threading.RLock()
    clipboard.staging_dir = str(tmp_path / 'clipboard')
    clipboard.adapter = Mock()
    clipboard._os_alias = 'linux'
    clipboard._macos_console_identity = None
    artifacts = env.artifacts
    artifacts.get_artifact_by_id = lambda _id: {'artifact_type':'shared', 'original_name':'shared.bin'}
    artifacts.get_artifact_file_path = lambda _id: str(shared)
    def stage_local_file(path, name):
        staged.write_bytes(Path(path).read_bytes())
        return str(staged), staged.name
    artifacts.stage_local_file = stage_local_file
    artifacts.build_upload_temp_download_relative_url = lambda _path: url
    artifacts.get_upload_temp_file_path = lambda _id, _name: str(staged)
    artifacts.cleanup_upload_temp_file = lambda path: Path(path).unlink()
    def set_clipboard(client_id, payload, *, action, arguments, tab_id):
        assert action == 'set_artifact_file' and tab_id == 'inline-tab'
        owner = inline_owner(env, 'control', domain=ControlDomain.CLIPBOARD, action=ClipboardAction.SET, payload=payload)
        status, result = clipboard.execute(owner, ClipboardAction.SET, payload)
        assert status == 1, result
        return result
    api = WebClipboardApi(SimpleNamespace(get_capabilities=lambda _: {'capabilities':{'files':True}}, set_clipboard=set_clipboard), artifacts)
    api.set_artifact_file('client-1', 'shared-artifact', tab_id='inline-tab')
    assert not staged.exists() and shared.read_bytes() == b'shared artifact'
    assert Path(clipboard.adapter.set_files.call_args.args[0][0]).read_bytes() == b'shared artifact'
    wait_until(lambda: bool(env.transfers.list_transfers()['recent']))
    assert env.transfers.list_transfers()['recent'][0]['state'] == 'completed'
