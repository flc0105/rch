"""Intentional Bind termination and mTLS listener identity configuration."""
import hashlib
import importlib.util
import shutil
import ssl
import sys
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest


def test_bind_disconnect_records_intent_before_closing_socket():
    from server.runtime.bind_connector import BindConnector
    events = []
    client_id = 'client-1'
    class _Socket:
        def shutdown(self, how):
            events.append('shutdown')
    class _Session:
        session_info = SimpleNamespace(client_id=client_id)
        transport = SimpleNamespace(socket=_Socket())
        def note_server_disconnect(self, command=''):
            events.append(('reason', command))
        def close(self):
            events.append('closed')
    session = _Session()
    connector = BindConnector(SimpleNamespace(connections=[session]))
    connector._sessions[('127.0.0.1', 9443)] = session
    assert connector.disconnect(client_id) == client_id
    assert events == [('reason', 'disconnect'), 'shutdown', 'closed']
    assert ('127.0.0.1', 9443) not in connector._sessions


def test_mtls_listener_lists_without_legacy_fingerprint(tmp_path):
    if not shutil.which('openssl'):
        pytest.skip('openssl is unavailable')
    server = SimpleNamespace(address=('127.0.0.1', 19989), connections=SimpleNamespace(all=lambda: []))
    from server.runtime.listener_manager import ListenerManager
    manager = ListenerManager(server, config_path=str(tmp_path / 'listeners.json'))
    manager.identities.initialize()
    listener = manager.create({'name': 'Local mTLS', 'protocol': 'mtls_tcp',
                               'host': '127.0.0.1', 'port': 19990})
    rows = manager.list()
    mtls = next(row for row in rows if row['id'] == listener['id'])
    assert mtls['protocol_label'] == 'mTLS/TCP'
    assert 'tls_fingerprint' not in mtls
    assert manager.build_settings(listener['id'], 19990, 'python')['listener_protocol'] == 'mtls_tcp'
    with pytest.raises(ValueError, match='Unsupported listener protocol'):
        manager.create({'name': 'Old TLS', 'protocol': 'tls_tcp', 'host': '127.0.0.1', 'port': 19991})


def test_intentional_bind_close_overrides_transport_eof_in_history(monkeypatch):
    from server.application.connection import connection_service as connection_module
    monkeypatch.setattr(connection_module, 'get_control_command_store', lambda: SimpleNamespace(
        take_delivered_shutdown=lambda _client_id: None))
    from server.application.connection.connection_service import WebConnectionService
    service = WebConnectionService.__new__(WebConnectionService)
    service.recent_device_store = None
    service.connection_history_store = SimpleNamespace(record_disconnected=Mock())
    service.client_session_token_service = None
    service.transfer_service = SimpleNamespace(fail_active_transfers_for_client=Mock())
    service.publish_connection_offline = Mock()
    service.serialize_connection = lambda _session: {'client_id': 'bind-1', 'machine_id': 'machine-1'}
    def _disconnect_api():
        return SimpleNamespace(handle_client_disconnected=Mock())
    service.server = SimpleNamespace(
        lifecycle_adapter=None,
        web_service=SimpleNamespace(
            terminal_api=SimpleNamespace(pty_session_service=_disconnect_api()),
            screen_view_api=SimpleNamespace(screen_view_session_service=_disconnect_api()),
            device_monitor_api=SimpleNamespace(device_monitor_session_service=_disconnect_api()),
            transfer_api=_disconnect_api(),
        ),
    )
    session = SimpleNamespace(
        session_info=SimpleNamespace(client_id='bind-1'),
        services=SimpleNamespace(heartbeat_service=SimpleNamespace(mark_disconnected=Mock())),
        context=SimpleNamespace(
            server_disconnect_request={'at': time.monotonic(), 'command': 'disconnect'},
            client_session_end=None,
            transport_failure={'reason': 'connection_lost', 'detail': {}},
        ),
    )
    service.handle_connection_closed(session)
    assert service.connection_history_store.record_disconnected.call_args.kwargs == {
        'termination_reason': 'server_requested_disconnect',
        'details': {'command': 'disconnect'},
    }
    service.publish_connection_offline.assert_called_once_with(
        session, termination_reason='server_requested_disconnect')
