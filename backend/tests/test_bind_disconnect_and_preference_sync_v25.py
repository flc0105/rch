"""Regression coverage for Bind disconnect and server preference roundtrips."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.application.preferences.terminal_context_preference_store import TerminalContextPreferenceStore
from server.application.preferences.toolbar_preference_store import ToolbarPreferenceStore
from server.application.connection.connection_service import WebConnectionService
from client.app.client import Client


from server.persistence.rch_database import RchDatabase


@pytest.fixture
def database(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    yield db
    db.close_thread_connection()


def test_connection_direction_is_preserved_through_database_roundtrip(database):
    store = TerminalContextPreferenceStore(database)
    selection = ['status', 'connection_direction', 'pid', 'connection_direction', 'bad field']
    assert store.save_preferences({'field_ids': selection}) == {
        'field_ids': ['status', 'connection_direction', 'pid'],
    }
    new_store = TerminalContextPreferenceStore(database)
    assert new_store.get_preferences()['field_ids'] == ['status', 'connection_direction', 'pid']
    assert store.save_preferences({'field_ids': []}) == {'field_ids': []}
    assert new_store.get_preferences() == {'field_ids': []}


def test_toolbar_catalog_is_not_duplicated_by_server(database):
    store = ToolbarPreferenceStore(database)
    saved = store.save_preferences({
        'toolbar': ['remote-files', 'log-viewer', 'documents', 'log-viewer'],
        'more': ['jobs', 'documents', 'one-liners'],
        'quick_actions_pinned': [{'platform': 'mac', 'alias': 'qa'}],
        'toolbox_shortcuts': [{'kind': 'script', 'script_name': 'hello', 'icon': 'file-code'}],
    })
    assert saved['toolbar'] == ['remote-files', 'log-viewer', 'documents']
    assert saved['more'] == ['jobs', 'one-liners']
    assert ToolbarPreferenceStore(database).get_preferences() == saved


def test_bind_disconnect_only_closes_session_and_reverse_keeps_existing_behavior():
    service = WebConnectionService.__new__(WebConnectionService)
    bind_session = SimpleNamespace(listener_protocol='bind_tcp', request_disconnect=Mock())
    reverse_session = SimpleNamespace(listener_protocol='tcp', request_disconnect=Mock())
    sessions = {'b': bind_session, 'r': reverse_session}
    service.server = SimpleNamespace(get_target_connection_by_client_id=lambda client_id: sessions[client_id])
    connector = SimpleNamespace(disconnect=Mock())

    assert service.disconnect_connection('b', connector)['mode'] == 'bind'
    connector.disconnect.assert_called_once_with('b')
    bind_session.request_disconnect.assert_not_called()
    assert service.disconnect_connection('r', connector)['mode'] == 'reverse'
    reverse_session.request_disconnect.assert_called_once_with()


def test_initial_bind_handshake_socket_failure_enters_recovery_without_exiting():
    connection = Mock(side_effect=OSError('Connection closed'))
    recovery = Mock()
    client = SimpleNamespace(
        connect=connection,
        connection_lifecycle=SimpleNamespace(is_bind_mode=True),
        _recover_from_connection_error=recovery,
    )
    Client.connect_initial(client)
    recovery.assert_called_once()
    assert str(recovery.call_args.args[0]) == 'Connection closed'


def test_reverse_initial_socket_failure_remains_error():
    recovery = Mock()
    client = SimpleNamespace(
        connect=Mock(side_effect=OSError('Connection closed')),
        connection_lifecycle=SimpleNamespace(is_bind_mode=False),
        _recover_from_connection_error=recovery,
    )
    with pytest.raises(OSError, match='Connection closed'):
        Client.connect_initial(client)
    recovery.assert_not_called()
