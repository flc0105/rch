import threading
from types import SimpleNamespace

import pytest

from server.connection.connection_manager import ConnectionManager
from server.runtime.session_acceptor import SessionAcceptor


class _Session:
    def __init__(self, client_id, address):
        self.session_info = SimpleNamespace(client_id=client_id)
        self.context = SimpleNamespace(transport_failure=None)
        self.address = address
        self.runtime = SimpleNamespace(
            message_queue=SimpleNamespace(put=lambda *args: None),
        )


class _ConnectionApi:
    def __init__(self):
        self.closed = []

    def handle_connection_closed(self, session):
        self.closed.append(session)


def _acceptor(manager, api):
    server = SimpleNamespace(
        connections=manager,
        web_service=SimpleNamespace(connection_api=api),
    )
    return SessionAcceptor(server)


def test_old_session_close_cannot_cleanup_replacement_session():
    manager = ConnectionManager()
    api = _ConnectionApi()
    acceptor = _acceptor(manager, api)
    old_session = _Session('client-A', '127.0.0.1:1001')
    new_session = _Session('client-A', '127.0.0.1:1002')
    manager.add(old_session)
    manager.add(new_session)

    acceptor._handle_connection_closed(old_session)

    assert api.closed == []
    assert manager.get_by_client_id('client-A') is new_session


def test_current_session_cleanup_serializes_with_new_registration():
    manager = ConnectionManager()
    old_session = _Session('client-A', '127.0.0.1:1001')
    new_session = _Session('client-A', '127.0.0.1:1002')
    manager.add(old_session)
    callback_started = threading.Event()
    release_callback = threading.Event()
    registration_finished = threading.Event()

    def cleanup():
        callback_started.set()
        assert release_callback.wait(2)

    cleanup_thread = threading.Thread(
        target=lambda: manager.run_if_current(old_session, cleanup),
        daemon=True,
    )
    cleanup_thread.start()
    assert callback_started.wait(1)

    def register_replacement():
        manager.add(new_session)
        registration_finished.set()

    registration_thread = threading.Thread(target=register_replacement, daemon=True)
    registration_thread.start()
    assert not registration_finished.wait(0.05)

    release_callback.set()
    cleanup_thread.join(1)
    registration_thread.join(1)

    assert not cleanup_thread.is_alive()
    assert not registration_thread.is_alive()
    assert registration_finished.is_set()
    assert manager.get_by_client_id('client-A') is new_session


def test_replaced_session_cannot_publish_registered_side_effects():
    old_session = _Session('client-A', '127.0.0.1:1001')
    new_session = _Session('client-A', '127.0.0.1:1002')

    class ReplacingManager(ConnectionManager):
        def add(self, session):
            super().add(session)
            if session is old_session:
                super().add(new_session)

    manager = ReplacingManager()
    registered = []
    api = SimpleNamespace(
        create_web_connection=lambda *_args: old_session,
        handle_connection_registered=lambda session: registered.append(session),
    )
    server = SimpleNamespace(
        connections=manager,
        web_service=SimpleNamespace(connection_api=api),
    )
    acceptor = SessionAcceptor(server)

    with pytest.raises(RuntimeError, match='replaced before registration'):
        acceptor._register_connection(
            object(), ('127.0.0.1', 1001), {'client_id': 'client-A'}
        )

    assert registered == []
    assert manager.get_by_client_id('client-A') is new_session
