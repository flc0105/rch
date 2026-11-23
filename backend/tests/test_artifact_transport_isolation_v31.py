"""A failed Artifact lookup must not be treated as a broken RCH TCP connection."""
import socket
from types import SimpleNamespace

import pytest

from client.connection.server_connection import ServerConnection
from core.protocol.message_types import MSG_TYPE_TRANSFER_UPDATE
from server.application.history.lifecycle_adapter import LifecycleAdapter
from server.application.transfers.transfer_service import TransferService
from server.connection.client_session import ClientSession
from server.persistence.rch_database import RchDatabase


class _Coordinator:
    def __init__(self, artifact_service):
        self.history_store = SimpleNamespace(artifact_service=artifact_service)
        self.completed = []
        self.files = []
        self.history_store.append_file_for_connection = lambda *args: self.files.append(args)

    def finish(self, conn, entry_id, ok, *, status):
        self.completed.append((conn, entry_id, ok, status))


class _Catalog:
    def __init__(self, missing=False):
        self.missing = missing
        self.seen = []

    def get_artifact_by_id(self, artifact_id):
        self.seen.append(artifact_id)
        if self.missing:
            raise FileNotFoundError('artifact not found')
        return {'artifact_id': artifact_id}


class _EventBus:
    def publish(self, *_args, **_kwargs):
        return None


@pytest.mark.parametrize('missing,expected_status', [(True, 'error'), (False, 'success')])
def test_completed_transfer_activity_missing_artifact_stays_nonfatal(missing, expected_status, tmp_path):
    """Wrong Server Web URL yields a real ID on the wrong server, unknown here."""
    catalog = _Catalog(missing=missing)
    coordinator = _Coordinator(catalog)
    adapter = LifecycleAdapter(coordinator)
    transfers = TransferService(_EventBus(), RchDatabase(str(tmp_path / 'rch.db')))
    transfers.lifecycle_adapter = adapter
    session = object()
    transfer = transfers.create_transfer(client_id='linux-client', direction='client_to_server',
                                         filename='preview.txt', metadata={'source': 'remote_file_download'})
    transfer_id = transfer['transfer_id']
    adapter._transfers[transfer_id] = (session, 'activity-1')

    result = transfers.handle_client_update('linux-client', {
        'transfer_id': transfer_id, 'state': 'completed', 'stage': 'completed',
        'artifact_id': 'artifact-owned-by-other-server',
    })
    assert result['state'] == 'completed'  # HTTP accepted the file on that other Server.
    assert catalog.seen == ['artifact-owned-by-other-server']
    assert coordinator.completed == [(session, 'activity-1', not missing, expected_status)]
    assert bool(coordinator.files) is not missing


class _InboundTransport:
    def __init__(self, *messages):
        self.messages = iter(messages)
        self.address = ('127.0.0.1', 9443)

    def recv(self):
        return next(self.messages)


def test_server_session_dispatch_oserror_does_not_escape_as_transport_error():
    """The TCP read succeeds even when a business callback fails with OSError."""
    transport = _InboundTransport(
        {'type': MSG_TYPE_TRANSFER_UPDATE, 'transfer_id': 'first'},
        {'type': MSG_TYPE_TRANSFER_UPDATE, 'transfer_id': 'second'},
    )
    session = ClientSession(transport, {'id': 'linux-client', 'addr': 'local-test'})
    observed = []

    def on_update(data):
        observed.append(data['transfer_id'])
        if data['transfer_id'] == 'first':
            raise FileNotFoundError('artifact missing in Mac Server catalog')

    session.context.on_transfer_update = on_update
    session.recv_message()
    session.recv_message()
    assert observed == ['first', 'second']


def test_server_session_read_error_still_propagates():
    class BrokenTransport:
        def recv(self):
            raise socket.error('Connection closed')

    session = ClientSession(BrokenTransport(), {'id': 'linux-client'})
    with pytest.raises(OSError, match='Connection closed'):
        session.recv_message()


def test_client_business_dispatch_oserror_does_not_disconnect_receiver():
    """A rejected transfer_start belongs to the operation, not to TCP recv."""
    connection = object.__new__(ServerConnection)
    frames = iter([{'type': 'transfer_start', 'id': 1}, {'type': 'heartbeat', 'id': 2}])
    observed = []
    connection.recv = lambda: next(frames)

    def handle(data):
        observed.append(data['id'])
        if data['id'] == 1:
            raise OSError('cannot start transfer task')
        return None

    connection.handle_received_message = handle
    connection.recv_message()
    connection.recv_message()
    assert observed == [1, 2]


def test_client_read_error_still_propagates():
    connection = object.__new__(ServerConnection)
    connection.recv = lambda: (_ for _ in ()).throw(socket.error('Connection closed'))
    with pytest.raises(OSError, match='Connection closed'):
        connection.recv_message()


def test_two_misdirected_upload_completions_preserve_real_main_tcp_socket(tmp_path):
    """RCH frames stay usable despite two Artifact IDs from a different Web Server."""
    import threading
    from core.protocol.rchsocket import RCHSocket
    from server.connection.transport.client_transport import ClientTransport
    from server.runtime.session_acceptor import SessionAcceptor

    sender_sock, receiver_sock = socket.socketpair()
    sender = RCHSocket()
    sender.socket.close()
    sender.socket = sender_sock
    transport = ClientTransport(receiver_sock, ('local-test', 9443))
    try:
        catalog = _Catalog(missing=True)
        coordinator = _Coordinator(catalog)
        adapter = LifecycleAdapter(coordinator)
        transfers = TransferService(_EventBus(), RchDatabase(str(tmp_path / 'rch.db')))
        transfers.lifecycle_adapter = adapter
        session = ClientSession(transport, {'id': 'linux-client'})
        ids = []
        for _ in range(2):
            item = transfers.create_transfer(client_id='linux-client', direction='client_to_server',
                                             metadata={'source': 'remote_file_download'})
            transfer_id = item['transfer_id']
            adapter._transfers[transfer_id] = (session, f'activity-{len(ids)}')
            ids.append(transfer_id)

        seen = []
        completed = threading.Event()
        def on_transfer(data):
            transfers.handle_client_update('linux-client', data)
            seen.append(data['transfer_id'])
            if len(seen) == 2:
                completed.set()
        session.context.on_transfer_update = on_transfer

        closed = []
        acceptor = SessionAcceptor(SimpleNamespace())
        acceptor._handle_connection_closed = lambda _session, exc=None: closed.append(exc)
        reader = threading.Thread(target=acceptor.connection_handler, args=(session,), daemon=True)
        reader.start()
        for index, transfer_id in enumerate(ids):
            sender.send({'type': MSG_TYPE_TRANSFER_UPDATE, 'transfer_id': transfer_id,
                         'artifact_id': f'wrong-server-{index}',
                         'state': 'completed', 'stage': 'completed'})
        assert completed.wait(2), 'both completed updates should be handled without disconnect'
        assert reader.is_alive()
        assert closed == []
        assert seen == ids
        assert [result[3] for result in coordinator.completed] == ['error', 'error']
    finally:
        sender.close()
        reader.join(timeout=2)
        receiver_sock.close()
    assert len(closed) == 1
    assert str(closed[0]) == 'Connection closed'


def test_two_preview_requests_with_unknown_artifacts_fail_only_at_http_boundary(tmp_path):
    """Preview never turns a missing Mac Artifact into a Client socket failure."""
    from server.application.artifact.remote_file_service import WebRemoteFileService

    transfers = TransferService(_EventBus(), RchDatabase(str(tmp_path / 'rch.db')))
    requested = []

    class _Session:
        session_info = SimpleNamespace(hostname='linux-client')

        def send(self, message):
            requested.append(message)
            transfers.handle_client_update('linux-client', {
                'transfer_id': message['transfer_id'], 'state': 'completed',
                'artifact_id': 'saved-on-linux-not-mac',
            })

    session = _Session()
    execution = SimpleNamespace(get_connection=lambda client_id: session)
    catalog = _Catalog(missing=True)
    service = WebRemoteFileService(execution, catalog, transfers)
    for _ in range(2):
        with pytest.raises(FileNotFoundError, match='artifact not found'):
            service.preview_file('linux-client', '/tmp/preview.txt')
    assert len(requested) == 2
    assert [message['operation'] for message in requested] == ['client_to_server_preview'] * 2
    assert len(catalog.seen) == 2
