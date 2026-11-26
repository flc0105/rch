"""Client reconnect backoff and TLS admission-error messages."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.app.client import Client
from client.connection.lifecycle import ClientConnectionLifecycle
from client.connection.errors import ConnectionAuthenticationError


def test_client_reconnection_exponential_delay_and_reset(monkeypatch, caplog):
    sleeps=[]
    monkeypatch.setattr('client.app.client.time.sleep', sleeps.append)
    fake=SimpleNamespace(
        server=SimpleNamespace(client_session_token=''),
        connection_lifecycle=SimpleNamespace(is_paused=False,is_bind_mode=False,reset_connection=Mock()),
        connect=Mock(),
    )
    for expected in (5,10,20,30,30):
        Client._recover_from_connection_error(fake,ConnectionError('connection reset'))
        assert sleeps[-1]==expected
    assert 'connection reset' in caplog.text
    fake.server.client_session_token='accepted-session'
    Client._recover_from_connection_error(fake,ConnectionError('closed'))
    assert sleeps[-1]==5


def test_bind_reconnection_only_immediate_once_before_admission(monkeypatch):
    sleeps=[]
    monkeypatch.setattr('client.app.client.time.sleep',sleeps.append)
    fake=SimpleNamespace(
        server=SimpleNamespace(client_session_token=''),
        connection_lifecycle=SimpleNamespace(is_paused=False,is_bind_mode=True,reset_connection=Mock(),
                                             close_current_connection=Mock()),
        connect=Mock(),
    )
    Client._recover_from_connection_error(fake,ConnectionError('closed'))
    assert not sleeps  # Existing fast reaccept remains.
    Client._recover_from_connection_error(fake,ConnectionAuthenticationError('Client mTLS identity not authorized or revoked'))
    assert sleeps==[5]
    Client._recover_from_connection_error(fake,ConnectionAuthenticationError('Client mTLS identity not authorized or revoked'))
    assert sleeps==[5,10]
    assert fake.connection_lifecycle.close_current_connection.call_count == 2
    fake.server.client_session_token='accepted-session'
    Client._recover_from_connection_error(fake,ConnectionError('closed'))
    assert sleeps==[5,10]


def test_reverse_dial_retries_5_10_20_30_and_resets(monkeypatch):
    from client.connection import lifecycle as lifecycle_module
    sleeps=[]
    monkeypatch.setattr(lifecycle_module.time,'sleep',sleeps.append)
    connector=SimpleNamespace(validate=Mock(),connect=Mock(side_effect=[False,False,False,False,True]))
    monkeypatch.setattr(lifecycle_module,'get_connector',lambda name:connector)
    monkeypatch.setattr(lifecycle_module,'RUNTIME_CONFIG',{'connection_mode':'reverse','server_transport':'tcp'})
    fake=SimpleNamespace(address=('127.0.0.1',9999),
                         server=SimpleNamespace(close=Mock()))
    lifecycle=ClientConnectionLifecycle(fake)
    lifecycle.create_connection=lambda:SimpleNamespace(close=Mock())
    lifecycle.connect_socket()
    assert sleeps==[5,10,20,30]
    assert connector.connect.call_count==5


@pytest.fixture
def backoff_store(tmp_path, monkeypatch):
    from client.config import runtime_config
    from client.config.runtime_config_service import RuntimeConfigService
    monkeypatch.setenv('RUNTIME_CONFIG_PATH', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(runtime_config, 'RECONNECT_BACKOFF_MIN_SECONDS', 5)
    monkeypatch.setattr(runtime_config, 'RECONNECT_BACKOFF_MAX_SECONDS', 30)
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_KEYS', [])
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_PATH', '')
    return RuntimeConfigService(), tmp_path / 'settings.json'


@pytest.mark.parametrize('minimum,maximum,expected', [
    (5, 30, [5, 10, 20, 30, 30]),
    (10, 60, [10, 20, 40, 60, 60]),
    (20, 30, [20, 30, 30, 30, 30]),
    (29, 30, [29, 30, 30, 30, 30]),
    (30, 30, [30] * 5),
    (60, 60, [60] * 5),
])
def test_configured_reconnect_sequence(backoff_store, minimum, maximum, expected):
    from client.connection.lifecycle import next_reconnect_delay
    service, _ = backoff_store
    service.set_config_value('RECONNECT_BACKOFF_MAX_SECONDS', maximum, typed=True)
    service.set_config_value('RECONNECT_BACKOFF_MIN_SECONDS', str(minimum))
    delay = 0
    for wanted in expected:
        delay = next_reconnect_delay(delay)
        assert delay == wanted
    assert next_reconnect_delay() == minimum


def test_backoff_pair_validation_and_reset(backoff_store):
    import json
    from client.config.runtime_config_service import reconnect_backoff_bounds
    service, path = backoff_store
    min_key = 'RECONNECT_BACKOFF_MIN_SECONDS'
    max_key = 'RECONNECT_BACKOFF_MAX_SECONDS'
    service.set_config_value(max_key, '60')
    service.set_config_value(min_key, '60')
    assert reconnect_backoff_bounds() == (60, 60)
    saved = path.read_bytes()
    for key, value in [(min_key, '61'), (max_key, '59'), (min_key, '0'),
                       (min_key, '1.5'), (max_key, '2147483648')]:
        with pytest.raises(ValueError):
            service.set_config_value(key, value)
    with pytest.raises(ValueError):
        service.set_config_value(min_key, True, typed=True)
    with pytest.raises(ValueError):
        service.reset_config_key(max_key)
    assert path.read_bytes() == saved
    assert reconnect_backoff_bounds() == (60, 60)
    assert json.loads(saved)[min_key] == 60
    service.reset_config_key(min_key)
    service.reset_config_key(max_key)
    assert reconnect_backoff_bounds() == (5, 30)
    assert not path.exists()
    keys = {item['key'] for item in service.build_config_payload()['items']}
    assert {min_key, max_key} <= keys
    assert 'RECONNECT_INTERVAL_SECONDS' not in keys
    with pytest.raises(KeyError):
        service.set_config_value('RECONNECT_INTERVAL_SECONDS', '10')


def test_backoff_uses_latest_bounds(backoff_store):
    from client.connection.lifecycle import next_reconnect_delay
    service, _ = backoff_store
    delay = next_reconnect_delay()
    service.set_config_value('RECONNECT_BACKOFF_MAX_SECONDS', '8')
    assert next_reconnect_delay(delay) == 8
    service.set_config_value('RECONNECT_BACKOFF_MAX_SECONDS', '60')
    service.set_config_value('RECONNECT_BACKOFF_MIN_SECONDS', '25')
    assert next_reconnect_delay(8) == 25
    service.reset_all_overrides()
    assert next_reconnect_delay() == 5


def test_invalid_saved_backoff_pair_is_not_reactivated(backoff_store):
    import json
    from client.config import runtime_config
    service, path = backoff_store
    path.write_text(json.dumps({'RECONNECT_BACKOFF_MIN_SECONDS': 60,
                                'RECONNECT_BACKOFF_MAX_SECONDS': 30,
                                'SERVER_INBOUND_TIMEOUT_SECONDS': 180}))
    assert runtime_config.effective_runtime_overrides() == {'SERVER_INBOUND_TIMEOUT_SECONDS': 180}
    before = path.read_bytes()
    assert service.get_default_values()['RECONNECT_BACKOFF_MIN_SECONDS'] == 5
    assert path.read_bytes() == before
    service.set_config_value('RECONNECT_BACKOFF_MAX_SECONDS', '90')
    assert runtime_config.effective_runtime_overrides() == {
        'RECONNECT_BACKOFF_MAX_SECONDS': 90, 'SERVER_INBOUND_TIMEOUT_SECONDS': 180}
