"""Regression coverage for role-separated RCH mTLS identities."""
import io
import os
import shutil
import socket
import ssl
import stat
import threading
import zipfile

import pytest

from client.connection.mtls import create_context
from client.connection.transport_connectors import get_connector
from server.runtime.identity_store import IdentityStore
from server.runtime.listener_protocols import get_listener_protocol, list_listener_protocols


@pytest.fixture
def provisioned(tmp_path):
    if not shutil.which('openssl'):
        pytest.skip('OpenSSL executable is required to provision mTLS identities')
    store = IdentityStore(tmp_path / 'identities')
    assert store.status() == {'initialized': False, 'clients': []}
    store.initialize()
    issued = store.create_client('test installation', 7)
    client_dir = tmp_path / 'installed-identity'
    client_dir.mkdir()
    with zipfile.ZipFile(store.download(issued['id'])) as archive:
        assert sorted(archive.namelist()) == ['client.crt', 'client.key', 'server-ca.crt']
        archive.extractall(client_dir)
    if os.name == 'posix':
        (client_dir / 'client.key').chmod(0o600)
    return store, issued, {'identity_dir': str(client_dir)}


def _pair_handshake(server, config, *, reverse):
    """Exercise TLS in both socket directions over a connected socket pair."""
    s1, s2 = socket.socketpair()
    receiver = server.context(server_side=reverse)
    caller = create_context(config, server_side=not reverse)
    finished = {}

    def server_thread():
        try:
            with receiver.wrap_socket(s1, server_side=reverse) as sock:
                server.verify_client(sock.getpeercert(binary_form=True))
                sock.sendall(b'OK')
                finished['server'] = True
        except Exception as exc:
            finished['server_error'] = exc
        finally:
            s1.close()

    thread = threading.Thread(target=server_thread)
    thread.start()
    try:
        with caller.wrap_socket(s2, server_side=not reverse, server_hostname=None) as sock:
            finished['received'] = sock.recv(2)
    except (ssl.SSLError, OSError) as exc:
        finished['client_error'] = exc
    finally:
        s2.close()
    thread.join(timeout=10)
    assert not thread.is_alive(), 'mTLS handshake stalled'
    return finished


@pytest.mark.parametrize('reverse', [True, False])
def test_mutual_auth_reverse_and_bind(provisioned, reverse):
    store, issued, config = provisioned
    result = _pair_handshake(store, config, reverse=reverse)
    assert result == {'received': b'OK', 'server': True}
    assert issued['expires_at']


@pytest.mark.parametrize('reverse', [True, False])
def test_revocation_rejects_new_connections(provisioned, reverse):
    store, issued, config = provisioned
    store.revoke(issued['id'])
    with pytest.raises(ValueError, match='revoked'):
        store.download(issued['id'])
    result = _pair_handshake(store, config, reverse=reverse)
    assert 'server_error' in result
    assert 'not authorized or revoked' in str(result['server_error'])
    assert result.get('received') != b'OK'


def test_no_implicit_identity_provisioning_or_downgrade(tmp_path):
    config = {'identity_dir': str(tmp_path / 'does-not-exist')}
    # Cleartext transport is independent from trust material.
    get_connector('tcp').validate(config)
    with pytest.raises(FileNotFoundError, match='identity file missing'):
        get_connector('mtls_tcp').validate(config)
    with pytest.raises(ValueError, match='Unsupported listener protocol'):
        get_listener_protocol('tls_tcp')
    assert {row['id'] for row in list_listener_protocols()} == {'tcp', 'mtls_tcp'}
    assert not (tmp_path / 'does-not-exist').exists()


def test_invalid_private_key_permissions_fail_closed(provisioned):
    store, issued, config = provisioned
    key = os.path.join(config['identity_dir'], 'client.key')
    if os.name != 'posix':
        pytest.skip('POSIX key mode checks')
    os.chmod(key, 0o644)
    with pytest.raises(PermissionError, match='private key'):
        create_context(config, server_side=False)


def test_initialize_does_not_reset_identity_trust(provisioned):
    store, issued, config = provisioned
    original = (store._path('server-ca.crt'))
    with open(original, 'rb') as f:
        trust_before = f.read()
    store.initialize()
    with open(original, 'rb') as f:
        assert f.read() == trust_before
    assert store.status()['clients'][0]['id'] == issued['id']
    assert not any('fingerprint' in client for client in store.status()['clients'])


def test_legacy_tls_listener_is_rejected_without_modifying_file(tmp_path):
    import json
    from types import SimpleNamespace
    pytest.importorskip('werkzeug', reason='Server config requires Werkzeug')
    from server.runtime.listener_manager import ListenerManager
    config_path = tmp_path / 'listeners.json'
    config_path.write_text(json.dumps([
        {'id': 'tcp-default', 'name': 'TCP', 'protocol': 'tcp',
         'host': '127.0.0.1', 'port': 19337, 'enabled': True},
        {'id': 'old-secure', 'name': 'Previously TLS', 'protocol': 'tls_tcp',
         'host': '127.0.0.1', 'port': 19338, 'enabled': True},
    ]), encoding='utf-8')
    before = config_path.read_bytes()
    server = SimpleNamespace(address=('127.0.0.1', 19337),
                             connections=SimpleNamespace(all=lambda: []))
    with pytest.raises(ValueError, match='Unsupported listener protocol'):
        ListenerManager(server, config_path=str(config_path))
    assert config_path.read_bytes() == before
    assert not (tmp_path / 'identities').exists()


def test_server_outbound_mtls_clears_handshake_deadline(provisioned):
    store, issued, config = provisioned
    outbound, inbound = socket.socketpair()
    result = {}

    def accept():
        try:
            with create_context(config, server_side=True).wrap_socket(inbound, server_side=True) as accepted:
                result['received'] = accepted.recv(2)
        except Exception as exc:
            result['error'] = exc
        finally:
            inbound.close()

    thread = threading.Thread(target=accept)
    thread.start()
    try:
        outbound.settimeout(0.5)
        with store.wrap_outbound_socket(outbound) as secured:
            assert secured.gettimeout() is None
            secured.sendall(b'OK')
    finally:
        outbound.close()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert result == {'received': b'OK'}


def test_database_does_not_migrate_obsolete_target_table(tmp_path):
    import sqlite3
    from server.persistence.rch_database import RchDatabase

    db_path = tmp_path / 'rch.db'
    db = RchDatabase(str(db_path))
    connection = db.connection()
    connection.execute('ALTER TABLE saved_bind_targets DROP COLUMN transport')
    db.close_thread_connection()
    with pytest.raises(RuntimeError, match='incompatible schema for saved_bind_targets'):
        RchDatabase(str(db_path))
    with sqlite3.connect(db_path) as raw:
        columns = [row[1] for row in raw.execute('PRAGMA table_info(saved_bind_targets)')]
    assert 'transport' not in columns


@pytest.mark.parametrize('reverse', [True, False])
def test_untrusted_identity_cannot_join_session(provisioned, tmp_path, reverse):
    trusted_store, _, _ = provisioned
    untrusted_store = IdentityStore(tmp_path / 'untrusted-authority')
    untrusted_store.initialize()
    issued = untrusted_store.create_client('other authority', 7)
    client_dir = tmp_path / 'other-installation'
    client_dir.mkdir()
    with zipfile.ZipFile(untrusted_store.download(issued['id'])) as archive:
        archive.extractall(client_dir)
    if os.name == 'posix':
        (client_dir / 'client.key').chmod(0o600)
    # The other installation has its own trust root; neither direction may accept it.
    result = _pair_handshake(trusted_store, {'identity_dir': str(client_dir)}, reverse=reverse)
    assert result.get('received') != b'OK'
    assert 'server_error' in result or 'client_error' in result


def test_install_command_writes_all_identity_materials_without_download(tmp_path, provisioned):
    import subprocess
    import sys
    from pathlib import Path

    store, issued, config = provisioned
    command = store.install_command(issued['id'])
    assert command.startswith('python3 -c "')
    assert command.endswith('"')
    # Windows CMD uses double quotes for grouping; this Python payload has no
    # inner double quotes, percent expansion, or shell control characters.
    import ast
    script = command[len('python3 -c "'):-1]
    ast.parse(script)
    assert subprocess.list2cmdline(['python3', '-c', script]) == command
    assert len(command) < 8191
    assert not any(char in script for char in '"%!^&|<>')
    assert 'api/identities' not in command
    assert 'client.key' in command and 'server-ca.crt' in command
    home = tmp_path / '方良辰'  # Verify a non-ASCII Windows-style home name.
    home.mkdir()
    import os
    env = {**os.environ, 'HOME': str(home)}
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    installed = home / 'client_bundle' / 'identity'
    with zipfile.ZipFile(store.download(issued['id'])) as archive:
        for name in ('client.crt', 'client.key', 'server-ca.crt'):
            assert (installed / name).read_bytes() == archive.read(name)
    if os.name == 'posix':
        assert stat.S_IMODE((installed / 'client.key').stat().st_mode) == 0o600
        assert stat.S_IMODE(installed.stat().st_mode) == 0o700
    store.revoke(issued['id'])
    with pytest.raises(ValueError, match='revoked'):
        store.install_command(issued['id'])


def test_revoked_rejection_is_received_by_client_on_reverse(provisioned):
    from types import SimpleNamespace
    from client.connection.server_connection import ServerConnection
    from core.protocol.rchsocket import RCHSocket
    from server.runtime.server_listener import ServerListener

    store, issued, config = provisioned
    store.revoke(issued['id'])
    listener = ServerListener(SimpleNamespace(),
                              {'id':'test-mtls','name':'test-mtls','host':'127.0.0.1','port':0,
                               'protocol':'mtls_tcp'}, ssl_context=store.context(server_side=True),
                              verify_peer=store.verify_client)
    listener._bind_server_socket()
    host, port = listener.socket.socket.getsockname()
    errors=[]
    def serve_one():
        try:listener._accept_connection()
        except Exception as exc:errors.append(exc)
    t=threading.Thread(target=serve_one)
    t.start()
    try:
        with socket.create_connection((host,port),timeout=5) as raw:
            with create_context(config,server_side=False).wrap_socket(raw,server_hostname=None) as secured:
                framed=RCHSocket()
                framed.socket.close()
                framed.socket=secured
                payload=framed.recv()
                with pytest.raises(ConnectionError, match='Client mTLS identity not authorized or revoked'):
                    ServerConnection.recv_message(SimpleNamespace(recv=lambda: payload))
                assert payload['type']=='connection_rejected'
    finally:
        listener.socket.close()
        t.join(timeout=10)
    assert not t.is_alive()
    assert not errors


def test_revoked_rejection_is_received_by_client_on_bind(provisioned):
    from types import SimpleNamespace
    from core.protocol.rchsocket import RCHSocket
    from client.connection.server_connection import ServerConnection
    store,issued,config=provisioned
    store.revoke(issued['id'])
    outbound,inbound=socket.socketpair()
    captured=[]
    def server_side():
        try:store.wrap_outbound_socket(outbound)
        except ssl.SSLError as exc:captured.append(str(exc))
    t=threading.Thread(target=server_side)
    t.start()
    try:
        with create_context(config,server_side=True).wrap_socket(inbound,server_side=True) as secured:
            framed=RCHSocket()
            framed.socket.close()
            framed.socket=secured
            payload=framed.recv()
            with pytest.raises(ConnectionError,match='not authorized or revoked'):
                ServerConnection.recv_message(SimpleNamespace(recv=lambda: payload))
    finally:
        inbound.close()
        outbound.close()
        t.join(timeout=10)
    assert captured==['Client mTLS identity not authorized or revoked']
