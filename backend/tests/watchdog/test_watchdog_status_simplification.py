"""Watchdog status exports the setting, a single launchd flag, and real file paths."""
from unittest.mock import patch

from client.config import runtime_config
from client.watchdog.client_watchdog_manager import ClientWatchdogManager
from client.watchdog.watchdog_status import inactive_watchdog_worker_status


def test_watchdog_one_suppression_flag_and_saved_enabled():
    with patch('client.watchdog.client_watchdog_manager.is_launchd_managed_client', return_value=True), \
         patch.object(runtime_config, 'REMOTE_CONTROL_WATCHDOG_ENABLED', True):
        payload = ClientWatchdogManager('example').get_watchdog_status_payload()
    assert payload['client']['suppressed'] is True
    assert payload['remote_control_watchdog']['enabled'] is True
    assert payload['remote_control_watchdog']['worker_alive'] is False
    for section in payload.values():
        assert 'configured_enabled' not in section
        assert 'suppression_reason' not in section
        assert 'watchdogs_suppressed' not in section


def test_heartbeat_file_only_reported_when_created(tmp_path):
    manager = ClientWatchdogManager('example')
    file = tmp_path / 'heartbeat.json'
    manager._build_local_heartbeat_watchdog_heartbeat_file_path = lambda: str(file)
    assert manager.get_watchdog_status_payload()['local_heartbeat_watchdog']['heartbeat_file_path'] == ''
    file.write_text('\n', encoding='utf8')
    assert manager.get_watchdog_status_payload()['local_heartbeat_watchdog']['heartbeat_file_path'] == str(file)
    with patch('client.watchdog.watchdog_status.get_temp_category_dir', return_value=str(tmp_path)):
        inactive = inactive_watchdog_worker_status('example')
    assert inactive['local_heartbeat_watchdog']['heartbeat_file_path'] == ''
