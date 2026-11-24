"""Device connection and instance actions keep distinct lifecycle boundaries."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.application.connection.connection_service import WebConnectionService
from server.application.connection.recent_device_store import RecentDeviceStore
from server.application.connection.saved_bind_target_store import SavedBindTargetStore
from server.application.web.connection_api import WebConnectionApi
from server.connection.connection_manager import ConnectionManager
from server.persistence.rch_database import RchDatabase
from server.runtime.bind_connector import BindConnector


@pytest.fixture
def environment(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    connections = ConnectionManager()
    server = SimpleNamespace(connections=connections,
                             get_target_connection_by_client_id=connections.get_by_client_id)
    connector = BindConnector(server)
    recent = RecentDeviceStore(db)
    saved = SavedBindTargetStore(db)
    service = WebConnectionService(server, Mock(), Mock(), recent_device_store=recent)
    api = WebConnectionApi(service, bind_connector=connector, saved_bind_target_store=saved)
    try:
        yield db, connections, connector, recent, saved, api
    finally:
        db.close_thread_connection()


def session(client_id, machine_id='machine', protocol='tcp', target_id=''):
    return SimpleNamespace(session_info=SimpleNamespace(client_id=client_id, machine_id=machine_id),
                           listener_protocol=protocol, saved_bind_target_id=target_id,
                           request_disconnect=Mock(), close=Mock())


@pytest.mark.parametrize('protocol', ['tcp', 'tls_tcp', 'bind_tcp'])
def test_kill_instance_uses_existing_session_control(environment, protocol):
    _, connections, connector, _, _, api = environment
    active = session('client', protocol=protocol)
    connections.add(active)
    connector.disconnect = Mock()
    assert api.kill_instance('client') == {'client_id': 'client'}
    active.request_disconnect.assert_called_once_with()
    connector.disconnect.assert_not_called()
    active.close.assert_not_called()


def test_reverse_remove_only_offline_and_preserves_other_records(environment):
    db, connections, _, recent, saved, api = environment
    recent.upsert_from_connection({'client_id': 'old', 'machine_id': 'machine', 'connection_state': 'offline'})
    recent.upsert_from_connection({'client_id': 'other', 'machine_id': 'other-machine', 'connection_state': 'offline'})
    target = saved.save('127.0.0.1', 9443, 'http://localhost:8085')
    db.connection().execute("INSERT INTO connection_sessions(machine_id,client_id) VALUES ('machine','old')")
    active = session('new')
    connections.add(active)
    with pytest.raises(ValueError, match='Disconnect'):
        api.remove_connection('old', 'machine')
    # Omitted machine ID still resolves the cached machine identity.
    with pytest.raises(ValueError, match='Disconnect'):
        api.remove_connection('old')
    active.request_disconnect.assert_not_called()
    active.close.assert_not_called()
    connections.remove(active)
    result = api.remove_connection('old', 'machine')
    assert not result['was_online'] and result['recent_removed_count'] == 1
    assert [row['client_id'] for row in recent.list_recent_devices()] == ['other']
    assert saved.list_targets()[0]['target_id'] == target['target_id']
    assert db.connection().execute("SELECT COUNT(*) FROM connection_sessions WHERE client_id='old'").fetchone()[0] == 1
    # A new connection can appear again after removal.
    recent.upsert_from_connection({'client_id': 'old', 'machine_id': 'machine', 'connection_state': 'online'})
    assert {row['client_id'] for row in recent.list_recent_devices()} == {'old', 'other'}


def test_bind_remove_only_saved_target_and_never_kills(environment):
    _, connections, connector, recent, saved, api = environment
    a = saved.save('localhost', 9443, 'http://localhost:8085')
    b = saved.save('localhost', 9444, 'http://localhost:8085')
    recent.upsert_from_connection({'client_id': 'reverse', 'machine_id': 'machine', 'connection_state': 'offline'})
    active = session('bind', protocol='bind_tcp', target_id=a['target_id'])
    connections.add(active)
    connector._sessions[('localhost', 9443)] = active
    with pytest.raises(ValueError, match='Disconnect'):
        api.remove_bind_target(a['target_id'])
    # A different never-connected saved target is independently removable.
    assert api.remove_bind_target(b['target_id']) == {'target_id': b['target_id']}
    active.request_disconnect.assert_not_called()
    active.close.assert_not_called()
    connections.remove(active)
    connector._inflight.add(('localhost', 9443))
    with pytest.raises(ValueError, match='Disconnect'):
        api.remove_bind_target(a['target_id'])
    connector._inflight.clear()
    assert api.remove_bind_target(a['target_id']) == {'target_id': a['target_id']}
    assert not saved.list_targets()
    assert [row['client_id'] for row in recent.list_recent_devices()] == ['reverse']


def test_reconnect_only_bind(environment):
    _, connections, connector, _, _, api = environment
    connections.add(session('reverse'))
    connector.reconnect = Mock()
    with pytest.raises(ValueError, match='only available for Bind'):
        api.reconnect_connection('reverse')
    connector.reconnect.assert_not_called()
    connections.add(session('bind', protocol='bind_tcp'))
    connector.reconnect.return_value = session('bind', protocol='bind_tcp', target_id='target')
    assert api.reconnect_connection('bind') == {'client_id': 'bind', 'target_id': 'target', 'status': 'connected'}
    connector.reconnect.assert_called_once_with('bind')


def test_bind_duplicate_rejected_before_any_confirmation(monkeypatch):
    from client.config.config import RUNTIME_CONFIG
    from client.commands.shell.common import session as commands
    from client.commands.shell.standalone import spawn_elevated_instance as elevated
    monkeypatch.setitem(RUNTIME_CONFIG, 'connection_mode', 'bind')
    spawn = Mock(side_effect=AssertionError('must not spawn'))
    monkeypatch.setattr(commands, '_spawn_instance', spawn)
    monkeypatch.setattr(elevated, '_spawn_elevated_mac', spawn)
    monkeypatch.setattr(elevated, '_spawn_elevated_win', spawn)
    monkeypatch.setattr(commands, '_relaunch_instance', spawn)
    for handler in (commands.spawn_instance, elevated.spawn_elevated_instance, commands.relaunch_instance):
        status, message = handler(SimpleNamespace())
        assert status == 0 and 'not supported in Bind mode' in message
    spawn.assert_not_called()


def test_reverse_commands_keep_confirmation_metadata_and_usage(monkeypatch):
    from client.config.config import RUNTIME_CONFIG
    from client.commands.shell.common import session as commands
    from client.commands.shell.standalone import spawn_elevated_instance as elevated
    from client.commands.runtime.manifest_metadata import command_metadata
    monkeypatch.setitem(RUNTIME_CONFIG, 'connection_mode', 'reverse')
    # Use a test double, never launch a process in the test.
    launch = Mock(return_value=(1, 'ok'))
    monkeypatch.setattr(elevated, '_spawn_elevated_mac', launch)
    owner = SimpleNamespace(command_platform='mac')
    assert elevated.spawn_elevated_instance(owner, '--no-confirm') == (1, 'ok')
    launch.assert_called_once_with()
    assert elevated.spawn_elevated_instance(owner, '--no-confirm invalid') == (
        0, 'Usage: spawn_elevated_instance [--no-confirm]')
    assert command_metadata(elevated.spawn_elevated_instance, platform='mac')['confirmation'] is True
    assert command_metadata(elevated.spawn_elevated_instance, platform='mac')['timeout'] == 150
    assert command_metadata(commands.relaunch_instance)['confirmation'] is True


def test_bind_remove_during_reconnect_of_edited_target_is_rejected(environment):
    _, _, connector, _, saved, api = environment
    target = saved.save('localhost', 9444, 'http://localhost:8085')
    connector._reconnecting_targets.add(target['target_id'])
    with pytest.raises(ValueError, match='Disconnect'):
        api.remove_bind_target(target['target_id'])
    assert saved.list_targets()[0]['target_id'] == target['target_id']
