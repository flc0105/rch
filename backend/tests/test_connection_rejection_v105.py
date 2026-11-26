"""Fail closed on explicitly rejected identities and invalid local configuration."""
import ssl
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.app.client import Client
from client.connection import lifecycle
from client.connection.errors import (
    ConnectionAuthenticationError, ConnectionConfigurationError,
    ConnectionTLSRejectionError, terminal_connection_error,
)
from client.connection.server_connection import ServerConnection


@pytest.mark.parametrize('error', [TimeoutError('timeout'), ConnectionResetError('reset'),
                                   ssl.SSLEOFError(8, 'EOF'), OSError('closed')])
def test_network_failure_is_not_authentication(error):
    assert terminal_connection_error(error) is None


def test_peer_certificate_and_explicit_tls_alert_are_terminal():
    assert isinstance(terminal_connection_error(ssl.SSLCertVerificationError(1, 'verify')), ConnectionAuthenticationError)
    alert = ssl.SSLError(1, 'peer rejected')
    alert.reason = 'TLSV1_ALERT_UNKNOWN_CA'
    assert isinstance(terminal_connection_error(alert), ConnectionTLSRejectionError)


def test_reverse_explicit_rejection_never_reconnects(monkeypatch):
    monkeypatch.setattr('client.app.client.time.sleep', Mock(side_effect=AssertionError('unexpected sleep')))
    fake = SimpleNamespace(server=SimpleNamespace(client_session_token=''),
                           connection_lifecycle=SimpleNamespace(is_bind_mode=False,
                               close_current_connection=Mock(), reset_connection=Mock()),
                           connect=Mock())
    with pytest.raises(ConnectionAuthenticationError, match='revoked'):
        Client._recover_from_connection_error(fake, ConnectionAuthenticationError('revoked'))
    fake.connect.assert_not_called()
    fake.connection_lifecycle.reset_connection.assert_not_called()
    fake.connection_lifecycle.close_current_connection.assert_called_once()


def test_explicit_rejection_frame_is_not_dispatched():
    fake = SimpleNamespace(recv=Mock(return_value={'type': 'connection_rejected', 'message': 'revoked'}),
                           handle_received_message=Mock())
    with pytest.raises(ConnectionAuthenticationError, match='revoked'):
        ServerConnection.recv_message(fake)
    fake.handle_received_message.assert_not_called()


@pytest.mark.parametrize('cause', [ssl.SSLCertVerificationError(1, 'verify'),
                                   ConnectionConfigurationError('identity missing')])
def test_reverse_dial_terminal_failure_never_sleeps(monkeypatch, cause):
    monkeypatch.setattr(lifecycle.time, 'sleep', Mock(side_effect=AssertionError('unexpected sleep')))
    connector = SimpleNamespace(validate=Mock(), connect=Mock(side_effect=cause))
    monkeypatch.setattr(lifecycle, 'get_connector', lambda _: connector)
    monkeypatch.setattr(lifecycle, 'RUNTIME_CONFIG', {'connection_mode': 'reverse', 'server_transport': 'mtls_tcp'})
    fake = SimpleNamespace(address=('127.0.0.1', 9999), server=SimpleNamespace(close=Mock()))
    manager = lifecycle.ClientConnectionLifecycle(fake)
    with pytest.raises((ConnectionAuthenticationError, ConnectionConfigurationError)):
        manager.connect_socket()
    connector.connect.assert_called_once()
    fake.server.close.assert_called_once()


def test_missing_identity_is_local_configuration_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, 'RUNTIME_CONFIG', {'connection_mode': 'reverse', 'server_transport': 'mtls_tcp',
                                                   'identity_dir': str(tmp_path)})
    fake = SimpleNamespace(address=('127.0.0.1', 9999), server=SimpleNamespace(close=Mock()))
    with pytest.raises(ConnectionConfigurationError, match='identity file missing'):
        lifecycle.ClientConnectionLifecycle(fake).connect_socket()


def test_invalid_reverse_address_is_terminal(monkeypatch):
    monkeypatch.setattr(lifecycle, 'RUNTIME_CONFIG', {'connection_mode': 'reverse'})
    fake = SimpleNamespace(address=('127.0.0.1', 0))
    with pytest.raises(ConnectionConfigurationError, match='Invalid Reverse'):
        lifecycle.ClientConnectionLifecycle(fake).connect_socket()


def test_terminal_exit_stops_local_recovery_supervisor(monkeypatch):
    import rchclient
    from client.watchdog import process_recovery_watchdog
    from client.update import signals

    recovery = Mock()
    watchdog = Mock()
    client = SimpleNamespace(connect_initial=Mock(side_effect=ConnectionConfigurationError('identity missing')),
                             connection_lifecycle=Mock(), local_ipc=Mock(), watchdog_manager=watchdog,
                             server=Mock(), wait=Mock())
    monkeypatch.setattr(rchclient, 'install_client_file_logging', Mock())
    monkeypatch.setattr(rchclient, 'resolve_features', lambda: {'watchdog': True})
    monkeypatch.setattr(rchclient, 'Client', lambda *a, **kw: client)
    monkeypatch.setattr(process_recovery_watchdog, 'ProcessRecoveryWatchdogManager', lambda: recovery)
    monkeypatch.setattr(signals, 'set_recovery_manager', Mock())
    monkeypatch.setattr(signals, 'is_update_candidate', lambda: False)
    monkeypatch.setattr(rchclient.runtime_config, 'PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
    with pytest.raises(SystemExit) as exc:
        rchclient.main()
    assert exc.value.code == 1
    recovery.stop.assert_called_once()
    watchdog.stop.assert_called_once()
    client.connection_lifecycle.close_session.assert_called_once()
    client.connection_lifecycle.close_bind_listener.assert_called_once()
    client.local_ipc.stop.assert_called_once()
    client.server.report_session_end.assert_not_called()
    client.wait.assert_not_called()
