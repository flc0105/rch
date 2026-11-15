"""Configuration GET/SET/RESET share one Control result for CLI and Web."""
from types import SimpleNamespace

import pytest

from client.config import runtime_config
from client.config.manager import ConfigurationManager
from core.protocol.control import ConfigurationAction
from core.utils.configuration_cli import configuration_cli_items
from server.application.web.command_execution_api import WebCommandExecutionApi


@pytest.fixture
def isolated_runtime_config(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNTIME_CONFIG_PATH', str(tmp_path / 'settings.json'))
    for key in runtime_config._RUNTIME_CONFIG_DEFAULTS:
        monkeypatch.setattr(runtime_config, key, getattr(runtime_config, key))
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_KEYS', list(runtime_config._RUNTIME_CONFIG_OVERRIDE_KEYS))
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_PATH', runtime_config._RUNTIME_CONFIG_OVERRIDE_PATH)


def test_client_control_query_and_mutations_are_consistent(isolated_runtime_config):
    manager = ConfigurationManager(None, features={'watchdog': False})
    scope = SimpleNamespace(_checkpoint=lambda: None, emit_progress=lambda *_args, **_kwargs: None)

    status, get = manager.execute(scope, ConfigurationAction.GET, {})
    assert status == 1
    assert {k: get[k] for k in ('status', 'message')} == {
        'status': 'success', 'message': ''}
    assert get['data']['items'][0]['choices'] == []
    assert 'store_path' in get['data']
    assert list(configuration_cli_items(get['data'])[0]) == [
        'group', 'key', 'value', 'default']

    status, set_result = manager.execute(scope, ConfigurationAction.SET, {
        'key': 'SCRIPT_DEFAULT_TIMEOUT', 'value': 78})
    assert status == 1
    assert set(set_result) == {'event_type', 'status', 'message'}
    assert set_result['status'] == 'success'
    assert 'SCRIPT_DEFAULT_TIMEOUT updated:' in set_result['message']
    assert 'items' not in set_result and 'data' not in set_result

    status, refreshed = manager.execute(scope, ConfigurationAction.GET, {})
    assert status == 1
    assert next(item for item in refreshed['data']['items'] if item['key'] == 'SCRIPT_DEFAULT_TIMEOUT')['value'] == 78

    status, reset_result = manager.execute(scope, ConfigurationAction.RESET, {'key': 'SCRIPT_DEFAULT_TIMEOUT'})
    assert status == 1
    assert set(reset_result) == {'event_type', 'status', 'message'}
    assert 'reset to default' in reset_result['message']

    status, failure = manager.execute(scope, ConfigurationAction.SET, {'key': 'SCRIPT_DEFAULT_TIMEOUT', 'value': 'nonsense'})
    assert status == 0
    assert set(failure) == {'event_type', 'status', 'message'}
    assert failure['status'] == 'error'


class InMemoryRemote:
    def __init__(self):
        self.manager = ConfigurationManager(None, features={'watchdog': False})
        self.scope = SimpleNamespace(_checkpoint=lambda: None, emit_progress=lambda *_args, **_kwargs: None)

    def run_foreground_control(self, target, domain, action, payload, **kwargs):
        return self.manager.execute(self.scope, action, payload)


def test_web_uses_same_control_envelope_and_refetches_get(isolated_runtime_config):
    api = WebCommandExecutionApi(None, remote_execution_service=InMemoryRemote())
    get = api.get_runtime_config('test-client')
    assert get['status'] == 'success'
    assert get['data']['items'] and 'value_type' in get['data']['items'][0]

    changed = api.update_runtime_config('test-client', 'SCRIPT_DEFAULT_TIMEOUT', 78)
    assert changed['status'] == 'success'
    assert set(changed) == {'event_type', 'status', 'message'}
    after_set = api.get_runtime_config('test-client')['data']
    assert next(row for row in after_set['items'] if row['key'] == 'SCRIPT_DEFAULT_TIMEOUT')['value'] == 78

    reset = api.reset_runtime_config('test-client', 'SCRIPT_DEFAULT_TIMEOUT')
    assert reset['status'] == 'success'
    assert 'items' not in reset and 'data' not in reset

    with pytest.raises(RuntimeError, match='Invalid'):
        api.update_runtime_config('test-client', 'SCRIPT_DEFAULT_TIMEOUT', 'invalid')


def test_web_watchdog_returns_status_payload_without_envelope():
    class Remote:
        def run_foreground_control(self, target, domain, action, payload, **kwargs):
            assert (domain, action) == ('watchdog', 'status')
            return 1, {'event_type': 'completed', 'status': 'success',
                       'data': {'client': {'client_id': 'test-client'},
                                'remote_control_watchdog': {'worker_alive': False},
                                'local_heartbeat_watchdog': {},
                                'process_recovery_watchdog': {'supervisor_alive': False}}}

    api = WebCommandExecutionApi(None, remote_execution_service=Remote())
    response = api.get_watchdog_status('test-client')
    assert response['client']['client_id'] == 'test-client'
    assert 'event_type' not in response and 'data' not in response


def test_web_watchdog_rejects_missing_business_payload():
    class Remote:
        def run_foreground_control(self, *args, **kwargs):
            return 1, {'event_type': 'completed', 'status': 'success', 'message': 'ok'}

    api = WebCommandExecutionApi(None, remote_execution_service=Remote())
    with pytest.raises(RuntimeError, match='Invalid watchdog status response'):
        api.get_watchdog_status('test-client')
