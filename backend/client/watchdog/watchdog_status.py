"""Read-only inactive watchdog status, with no supervisor/monitor imports."""

import os
from client.config import runtime_config
from client.config.config import UPLOAD_BASE_URL
from client.runtime.temp_workspace import get_temp_category_dir
from client.watchdog.watchdog_paths import get_watchdog_log_path


def inactive_guard_status(client_id):
    client_id = str(client_id or '').strip()
    return {
        'client': {
            'id': client_id, 'pid': os.getpid(), 'watchdog_supported': False,
            'lifecycle_manager': '', 'watchdogs_suppressed': False,
        },
        'remote_watchdog': {
            'enabled': False, 'configured_enabled': bool(runtime_config.REMOTE_HTTP_WATCHDOG_ENABLED),
            'suppressed': True, 'suppression_reason': 'feature_disabled',
            'worker_pid': None, 'worker_alive': False,
            'control_url': f'{UPLOAD_BASE_URL}/api/connections/{client_id}/control',
            'interval_seconds': runtime_config.REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS,
            'log_path': get_watchdog_log_path('client_remote_watchdog.log'),
        },
        'local_watchdog': {
            'enabled': False, 'configured_enabled': bool(runtime_config.LOCAL_WATCHDOG_ENABLED),
            'suppressed': True, 'suppression_reason': 'feature_disabled',
            'worker_pid': None, 'worker_alive': False,
            'heartbeat_interval_seconds': runtime_config.LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS,
            'timeout_seconds': runtime_config.LOCAL_WATCHDOG_TIMEOUT_SECONDS,
            'heartbeat_file_path': os.path.join(
                get_temp_category_dir('watchdog_heartbeats', private=True),
                f'client_local_watchdog_heartbeat_{client_id}.json',
            ),
            'log_path': get_watchdog_log_path('client_local_watchdog.log'),
            'feeder_thread_name': None, 'feeder_alive': False,
        },
    }


def inactive_process_status():
    return {
        'enabled': False, 'configured_enabled': bool(runtime_config.PROCESS_WATCHDOG_ENABLED),
        'suppressed': True, 'suppression_reason': 'feature_disabled',
        'supervisor_pid': None, 'supervisor_alive': False,
        'poll_interval_seconds': 0.5,
        'log_path': get_watchdog_log_path('process_watchdog.log'),
    }
