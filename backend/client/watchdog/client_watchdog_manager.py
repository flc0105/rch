import os

from client.config import runtime_config

from client.config.config import UPLOAD_BASE_URL
from client.watchdog.watchdog_paths import get_watchdog_log_path, get_existing_watchdog_log_path
from client.watchdog.local_heartbeat_watchdog import LocalHeartbeatWatchdogFeeder
from client.watchdog.remote_control_watchdog import RemoteControlWatchdogMonitor
from client.watchdog.watchdog_process import ClientWatchdogProcess
from client.runtime.temp_workspace import get_temp_category_dir
from client.runtime.launch_context import is_launchd_managed_client
from core.utils.logger import logger


class ClientWatchdogManager:
    def __init__(self, client_id: str):
        self.client_id = str(client_id or '').strip()
        self._watchdog_process = None
        self._local_heartbeat_watchdog_feeder = None
        self._started = False
        self.local_ipc_environment = {}


    def _current_enabled_modes(self):
        return {
            'remote_control_watchdog': bool(runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED),
            'local_heartbeat_watchdog': bool(runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED),
        }

    def _build_local_heartbeat_watchdog_heartbeat_file_path(self):
        return os.path.join(get_temp_category_dir('watchdog_heartbeats', private=True), f'client_local_heartbeat_watchdog_heartbeat_{self.client_id}.json')


    def _build_local_heartbeat_watchdog_log_file_path(self):
        return get_watchdog_log_path('client_local_heartbeat_watchdog.log')


    def _build_remote_control_watchdog_log_file_path(self):
        return get_watchdog_log_path('client_remote_control_watchdog.log')


    def _build_remote_http_control_url(self):
        return f'{UPLOAD_BASE_URL}/api/connections/{self.client_id}/control'


    def _ensure_local_heartbeat_watchdog_feeder(self):
        if self._local_heartbeat_watchdog_feeder is None:
            self._local_heartbeat_watchdog_feeder = LocalHeartbeatWatchdogFeeder(
                client_id=self.client_id,
                heartbeat_interval_seconds=runtime_config.LOCAL_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS,
                heartbeat_file_path=self._build_local_heartbeat_watchdog_heartbeat_file_path(),
                local_heartbeat_watchdog_log_file_path=self._build_local_heartbeat_watchdog_log_file_path(),
            )


    def _ensure_watchdog_process(self):
        if self._watchdog_process is None:
            self._watchdog_process = ClientWatchdogProcess(
                client_id=self.client_id,
                local_ipc_environment=self.local_ipc_environment,
                remote_control_watchdog_enabled=self._current_enabled_modes()['remote_control_watchdog'],
                remote_control_watchdog_base_url=UPLOAD_BASE_URL,
                remote_control_watchdog_interval_seconds=runtime_config.REMOTE_CONTROL_WATCHDOG_INTERVAL_SECONDS,
                remote_control_watchdog_log_file_path=self._build_remote_control_watchdog_log_file_path(),
                local_heartbeat_watchdog_enabled=self._current_enabled_modes()['local_heartbeat_watchdog'],
                local_heartbeat_watchdog_timeout_seconds=runtime_config.LOCAL_HEARTBEAT_WATCHDOG_TIMEOUT_SECONDS,
                local_heartbeat_watchdog_heartbeat_file_path=self._build_local_heartbeat_watchdog_heartbeat_file_path(),
                local_heartbeat_watchdog_log_file_path=self._build_local_heartbeat_watchdog_log_file_path(),
            )

    def _log_startup_once(self):
        items = [
            ('client_id', self.client_id),
            ('main_process_pid', os.getpid()),
            ('remote_control_watchdog_enabled', runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED),
            ('remote_control_watchdog_interval_seconds', runtime_config.REMOTE_CONTROL_WATCHDOG_INTERVAL_SECONDS),
            ('remote_http_control_url', self._build_remote_http_control_url()),
            ('remote_control_watchdog_log_file_path', self._build_remote_control_watchdog_log_file_path()),
            ('local_heartbeat_watchdog_enabled', runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED),
            ('local_heartbeat_watchdog_heartbeat_interval_seconds', runtime_config.LOCAL_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS),
            ('local_heartbeat_watchdog_timeout_seconds', runtime_config.LOCAL_HEARTBEAT_WATCHDOG_TIMEOUT_SECONDS),
            ('local_heartbeat_watchdog_heartbeat_file_path', self._build_local_heartbeat_watchdog_heartbeat_file_path()),
            ('local_heartbeat_watchdog_log_file_path', self._build_local_heartbeat_watchdog_log_file_path()),
        ]

        logger.info('Watchdog startup:')
        for key, value in items:
            logger.info(f'  {key}={value}')


    def start(self):
        if self._started:
            return

        # launchd owns restart/stop semantics for LaunchAgent and LaunchDaemon Clients.
        # Running another recovery layer here can revive a deliberately stopped job.
        if is_launchd_managed_client():
            self.stop()
            self._started = True
            return

        # self._log_startup_once()

        if self._current_enabled_modes()['local_heartbeat_watchdog']:
            self._ensure_local_heartbeat_watchdog_feeder()
            self._local_heartbeat_watchdog_feeder.start()

        if self._current_enabled_modes()['remote_control_watchdog'] or self._current_enabled_modes()['local_heartbeat_watchdog']:
            self._ensure_watchdog_process()
            self._watchdog_process.start()

        self._started = True


    def stop(self):
        if self._watchdog_process is not None:
            self._watchdog_process.stop()

        if self._local_heartbeat_watchdog_feeder is not None:
            self._local_heartbeat_watchdog_feeder.stop()

        # 配置热更新后的 restart 必须按最新 runtime_config 重建 watchdog。
        self._watchdog_process = None
        self._local_heartbeat_watchdog_feeder = None
        self._started = False


    def get_watchdog_status_payload(self):
        suppressed = is_launchd_managed_client()
        remote_configured = bool(self._current_enabled_modes()['remote_control_watchdog'])
        local_configured = bool(self._current_enabled_modes()['local_heartbeat_watchdog'])

        watchdog_worker_pid = None
        watchdog_worker_alive = False
        if not suppressed and self._watchdog_process is not None:
            watchdog_worker_pid = self._watchdog_process.get_pid()
            watchdog_worker_alive = self._watchdog_process.is_alive()

        heartbeat_file_path = self._build_local_heartbeat_watchdog_heartbeat_file_path()
        local_feeder_thread_alive = False
        local_feeder_thread_name = None
        if not suppressed and self._local_heartbeat_watchdog_feeder is not None:
            local_feeder_thread_alive = self._local_heartbeat_watchdog_feeder.is_alive()
            local_feeder_thread_name = self._local_heartbeat_watchdog_feeder.get_thread_name()

        return {
            'client': {
                'id': self.client_id,
                'pid': os.getpid(),
                'suppressed': suppressed,
            },
            # Remote and Local share the same worker; both sections expose its actual identity.
            'remote_control_watchdog': {
                'enabled': remote_configured,
                'worker_pid': watchdog_worker_pid,
                'worker_alive': watchdog_worker_alive,
                'control_url': self._build_remote_http_control_url(),
                'interval_seconds': runtime_config.REMOTE_CONTROL_WATCHDOG_INTERVAL_SECONDS,
                'log_path': get_existing_watchdog_log_path('client_remote_control_watchdog.log'),
            },
            'local_heartbeat_watchdog': {
                'enabled': local_configured,
                'worker_pid': watchdog_worker_pid,
                'worker_alive': watchdog_worker_alive,
                'heartbeat_interval_seconds': runtime_config.LOCAL_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS,
                'timeout_seconds': runtime_config.LOCAL_HEARTBEAT_WATCHDOG_TIMEOUT_SECONDS,
                'heartbeat_file_path': heartbeat_file_path if os.path.isfile(heartbeat_file_path) else '',
                'log_path': get_existing_watchdog_log_path('client_local_heartbeat_watchdog.log'),
                'feeder_thread_name': local_feeder_thread_name,
                'feeder_alive': local_feeder_thread_alive,
            },
        }