"""A missing process working directory must not break result or status frames."""
import os
import queue
import shutil
import shlex
from unittest.mock import Mock

import pytest

from client.config.feature_config import resolve_features
from client.connection.handshake import ClientInfoBuilder
from client.connection.server_connection import ServerConnection
from client.runtime.filesystem import path_resolver
from core.protocol.rchsocket import RCHSocket
from test_connections import _open_tcp_pair


@pytest.fixture
def connection(tmp_path, monkeypatch):
    original = os.getcwd()
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    features = resolve_features(overrides={
        'watchdog': False, 'pty': False, 'screen_view': False, 'clipboard': False,
    })
    client = ServerConnection(features=features)
    client.client_id = 'cwd-test'
    left, right = _open_tcp_pair()
    client.adopt_socket(left)
    peer = RCHSocket()
    peer.socket.close()
    peer.socket = right
    peer.socket.settimeout(3)
    try:
        yield client, peer, home
    finally:
        os.chdir(original)
        client.close()
        peer.close()


def remove_cwd(path):
    path.mkdir()
    os.chdir(path)
    shutil.rmtree(path)
    with pytest.raises(OSError):
        os.getcwd()


@pytest.mark.skipif(os.name != 'posix', reason='Deleting a process CWD requires POSIX semantics')
def test_shell_deletes_cwd_and_returns_result_on_same_socket(connection, tmp_path):
    client, peer, home = connection
    work = tmp_path / 'work'
    work.mkdir()
    os.chdir(work)
    original_socket = client.socket

    client.enqueue_pending_message({'type': 'command', 'id': 1,
                                    'text': 'shell rm -rf -- ' + shlex.quote(str(work))})
    client.send_result(*client.recv_command(timeout=1))
    packet = peer.recv()
    assert packet['id'] == 1 and packet['status'] == 'success'
    assert packet['cwd'] == str(home.resolve())
    assert not work.exists()
    assert client.socket is original_socket
    client.handle_received_message({'type': 'heartbeat', 'id': 2, 'ts': 'now'})
    assert peer.recv()['cwd'] == str(home.resolve())
    client.enqueue_pending_message({'type': 'command', 'id': 3, 'text': 'pwd'})
    client.send_result(*client.recv_command(timeout=1))
    packet = peer.recv()
    assert packet['status'] == 'success' and packet['message'].strip() == str(home.resolve())
    assert client.socket is original_socket


@pytest.mark.skipif(os.name != 'posix', reason='Deleting a process CWD requires POSIX semantics')
def test_status_and_stream_frames_do_not_change_cwd_during_execution(connection, tmp_path):
    client, peer, home = connection
    remove_cwd(tmp_path / 'work')
    client.send_event(1, {'event_type': 'chunk', 'message': 'still running'})
    assert peer.recv()['cwd'] == ''
    client.send_result(1, 1, 'done')
    assert peer.recv()['status'] == 'success'
    client.handle_received_message({'type': 'heartbeat', 'id': 2, 'ts': 'now'})
    assert peer.recv()['type'] == 'heartbeat_ack'
    client.handle_received_message({'type': 'cancel', 'id': 3, 'target_id': 99})
    assert peer.recv()['type'] == 'cancel_ack'
    with pytest.raises(OSError):
        os.getcwd()
    with pytest.raises(queue.Empty):
        client.recv_command(timeout=0.01)
    assert os.getcwd() == str(home.resolve())
    client.handle_received_message({'type': 'heartbeat', 'id': 4, 'ts': 'now'})
    assert peer.recv()['cwd'] == str(home.resolve())


@pytest.mark.skipif(os.name != 'posix', reason='Deleting a process CWD requires POSIX semantics')
def test_handshake_recovers_deleted_cwd(connection, tmp_path):
    client, peer, home = connection
    remove_cwd(tmp_path / 'work')
    info = ClientInfoBuilder(client.client_id, features=client.runtime.features).build()
    assert info['cwd'] == str(home.resolve())
    client.send(info)
    assert peer.recv()['cwd'] == str(home.resolve())


@pytest.mark.skipif(os.name != 'posix', reason='Deleting a process CWD requires POSIX semantics')
def test_external_deletion_before_command_uses_valid_directory(connection, tmp_path):
    client, peer, home = connection
    remove_cwd(tmp_path / 'work')
    client.enqueue_pending_message({'type': 'command', 'id': 1, 'text': 'pwd'})
    client.send_result(*client.recv_command(timeout=1))
    packet = peer.recv()
    assert packet['status'] == 'success' and packet['message'].strip() == str(home.resolve())


def test_recovery_preserves_valid_directory(connection, tmp_path, monkeypatch):
    _, _, home = connection
    os.chdir(home)
    change = Mock(side_effect=AssertionError('valid CWD must not be changed'))
    with monkeypatch.context() as patch:
        patch.setattr(path_resolver.os, 'chdir', change)
        assert path_resolver.recover_current_directory() == str(home.resolve())
    change.assert_not_called()


@pytest.mark.skipif(os.name != 'posix', reason='Deleting a process CWD requires POSIX semantics')
def test_recovery_uses_temp_when_home_missing(connection, tmp_path, monkeypatch):
    _, _, home = connection
    home.rmdir()
    fallback = tmp_path / 'fallback'
    fallback.mkdir()
    monkeypatch.setattr(path_resolver.tempfile, 'gettempdir', lambda: str(fallback))
    remove_cwd(tmp_path / 'work')
    assert path_resolver.recover_current_directory() == str(fallback.resolve())


def test_no_fallback_does_not_raise_or_interrupt_metadata(connection, monkeypatch):
    client, peer, _ = connection
    with monkeypatch.context() as patch:
        patch.setattr(path_resolver.os, 'getcwd', Mock(side_effect=FileNotFoundError('missing cwd')))
        patch.setattr(path_resolver.os, 'chdir', Mock(side_effect=PermissionError('not accessible')))
        assert path_resolver.recover_current_directory() == ''
        client.send_result(1, 1, 'done')
        assert peer.recv()['status'] == 'success'
        client.handle_received_message({'type': 'heartbeat', 'id': 2})
        assert peer.recv()['type'] == 'heartbeat_ack'
