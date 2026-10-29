"""The status/UI may only advertise Watchdog logs that actually exist."""

from client.watchdog import watchdog_paths
from client.watchdog import watchdog_status
from client.watchdog import client_watchdog_manager
from client.watchdog import process_recovery_watchdog


def test_watchdog_log_path_is_hidden_until_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog_paths, 'get_watchdog_log_path', lambda name: str(tmp_path / name))
    assert watchdog_paths.get_existing_watchdog_log_path('process_recovery_watchdog.log') == ''
    log = tmp_path / 'process_recovery_watchdog.log'
    log.write_text('', encoding='utf-8')
    assert watchdog_paths.get_existing_watchdog_log_path('process_recovery_watchdog.log') == str(log)
    log.unlink()
    assert watchdog_paths.get_existing_watchdog_log_path('process_recovery_watchdog.log') == ''


def test_watchdog_statuses_only_expose_created_logs(tmp_path, monkeypatch):
    def existing(name):
        path = tmp_path / name
        return str(path) if path.is_file() else ''

    for module in (client_watchdog_manager, watchdog_status, process_recovery_watchdog):
        monkeypatch.setattr(module, 'get_existing_watchdog_log_path', existing)

    manager = client_watchdog_manager.ClientWatchdogManager('client-xyz')
    report = manager.get_watchdog_status_payload()
    inactive = watchdog_status.inactive_watchdog_worker_status('client-xyz')
    process_report = process_recovery_watchdog.get_process_recovery_watchdog_status_payload()
    inactive_process = watchdog_status.inactive_process_recovery_watchdog_status()
    for payload in (report, inactive):
        assert payload['remote_control_watchdog']['log_path'] == ''
        assert payload['local_heartbeat_watchdog']['log_path'] == ''
    assert process_report['log_path'] == ''
    assert inactive_process['log_path'] == ''

    for name in ('client_remote_control_watchdog.log', 'client_local_heartbeat_watchdog.log', 'process_recovery_watchdog.log'):
        (tmp_path / name).write_text('log', encoding='utf-8')
    report = manager.get_watchdog_status_payload()
    assert report['remote_control_watchdog']['log_path'] == str(tmp_path / 'client_remote_control_watchdog.log')
    assert report['local_heartbeat_watchdog']['log_path'] == str(tmp_path / 'client_local_heartbeat_watchdog.log')
    assert process_recovery_watchdog.get_process_recovery_watchdog_status_payload()['log_path'] == str(tmp_path / 'process_recovery_watchdog.log')
