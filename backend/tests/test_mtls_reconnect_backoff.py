"""Client reconnect backoff and TLS admission-error messages."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.app.client import Client
from client.connection.lifecycle import ClientConnectionLifecycle


def test_client_reconnection_exponential_delay_and_reset(monkeypatch, caplog):
    sleeps=[]
    monkeypatch.setattr('client.app.client.time.sleep', sleeps.append)
    fake=SimpleNamespace(
        RECONNECT_INTERVAL=5,
        server=SimpleNamespace(client_session_token=''),
        connection_lifecycle=SimpleNamespace(is_paused=False,is_bind_mode=False,reset_connection=Mock()),
        connect=Mock(),
    )
    for expected in (5,10,20,30,30):
        Client._recover_from_connection_error(fake,ConnectionError('Client mTLS identity not authorized or revoked'))
        assert sleeps[-1]==expected
    assert 'Client mTLS identity not authorized or revoked' in caplog.text
    fake.server.client_session_token='accepted-session'
    Client._recover_from_connection_error(fake,ConnectionError('closed'))
    assert sleeps[-1]==5


def test_bind_reconnection_only_immediate_once_before_admission(monkeypatch):
    sleeps=[]
    monkeypatch.setattr('client.app.client.time.sleep',sleeps.append)
    fake=SimpleNamespace(
        RECONNECT_INTERVAL=5,server=SimpleNamespace(client_session_token=''),
        connection_lifecycle=SimpleNamespace(is_paused=False,is_bind_mode=True,reset_connection=Mock()),
        connect=Mock(),
    )
    Client._recover_from_connection_error(fake,ConnectionError('closed'))
    assert not sleeps  # Existing fast reaccept remains.
    Client._recover_from_connection_error(fake,ConnectionError('Client mTLS identity not authorized or revoked'))
    assert sleeps==[5]
    Client._recover_from_connection_error(fake,ConnectionError('Client mTLS identity not authorized or revoked'))
    assert sleeps==[5,10]
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
    fake=SimpleNamespace(RECONNECT_INTERVAL=5,address=('127.0.0.1',9999),
                         server=SimpleNamespace(close=Mock()))
    lifecycle=ClientConnectionLifecycle(fake)
    lifecycle.create_connection=lambda:SimpleNamespace(close=Mock())
    lifecycle.connect_socket()
    assert sleeps==[5,10,20,30]
    assert connector.connect.call_count==5
