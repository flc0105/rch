import os
import tempfile

from client.config.runtime_config import (
    LOCAL_WATCHDOG_ENABLED,
    LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS,
    LOCAL_WATCHDOG_TIMEOUT_SECONDS,
    REMOTE_HTTP_WATCHDOG_ENABLED,
    REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS,

)

from client.config.config import UPLOAD_BASE_URL
from client.watchdog.local_watchdog import LocalWatchdogHeartbeatFeeder
from client.watchdog.watchdog_process import ClientWatchdogProcess
from core.utils.logger import logger


class ClientGuardManager:
    def __init__(self, client_id: str):
        self.client_id = str(client_id or '').strip()
        self._watchdog_process = None
        self._local_watchdog_feeder = None
        self._started = False


    def _build_local_watchdog_heartbeat_file_path(self):
        return os.path.join(tempfile.gettempdir(), f'client_local_watchdog_heartbeat_{self.client_id}.json')


    def _build_local_watchdog_log_file_path(self):
        return os.path.join(tempfile.gettempdir(), f'client_local_watchdog.log')


    def _build_remote_watchdog_log_file_path(self):
        return os.path.join(tempfile.gettempdir(), f'client_remote_watchdog.log')


    def _build_remote_http_control_url(self):
        return f'{UPLOAD_BASE_URL}/api/connections/{self.client_id}/control'


    def _ensure_local_watchdog_feeder(self):
        if self._local_watchdog_feeder is None:
            self._local_watchdog_feeder = LocalWatchdogHeartbeatFeeder(
                client_id=self.client_id,
                heartbeat_interval_seconds=LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS,
                heartbeat_file_path=self._build_local_watchdog_heartbeat_file_path(),
                local_watchdog_log_file_path=self._build_local_watchdog_log_file_path(),
            )


    def _ensure_watchdog_process(self):
        if self._watchdog_process is None:
            self._watchdog_process = ClientWatchdogProcess(
                client_id=self.client_id,
                remote_http_watchdog_enabled=REMOTE_HTTP_WATCHDOG_ENABLED,
                remote_http_watchdog_base_url=UPLOAD_BASE_URL,
                remote_http_watchdog_interval_seconds=REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS,
                remote_watchdog_log_file_path=self._build_remote_watchdog_log_file_path(),
                local_watchdog_enabled=LOCAL_WATCHDOG_ENABLED,
                local_watchdog_timeout_seconds=LOCAL_WATCHDOG_TIMEOUT_SECONDS,
                local_watchdog_heartbeat_file_path=self._build_local_watchdog_heartbeat_file_path(),
                local_watchdog_log_file_path=self._build_local_watchdog_log_file_path(),
            )

    def _log_startup_once(self):
        items = [
            ('client_id', self.client_id),
            ('main_process_pid', os.getpid()),
            ('remote_http_watchdog_enabled', REMOTE_HTTP_WATCHDOG_ENABLED),
            ('remote_http_watchdog_interval_seconds', REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS),
            ('remote_http_control_url', self._build_remote_http_control_url()),
            ('remote_watchdog_log_file_path', self._build_remote_watchdog_log_file_path()),
            ('local_watchdog_enabled', LOCAL_WATCHDOG_ENABLED),
            ('local_watchdog_heartbeat_interval_seconds', LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS),
            ('local_watchdog_timeout_seconds', LOCAL_WATCHDOG_TIMEOUT_SECONDS),
            ('local_watchdog_heartbeat_file_path', self._build_local_watchdog_heartbeat_file_path()),
            ('local_watchdog_log_file_path', self._build_local_watchdog_log_file_path()),
        ]

        logger.info('Watchdog startup:')
        for key, value in items:
            logger.info(f'  {key}={value}')


    def start(self):
        if self._started:
            return

        # self._log_startup_once()

        if LOCAL_WATCHDOG_ENABLED:
            self._ensure_local_watchdog_feeder()
            self._local_watchdog_feeder.start()

        if REMOTE_HTTP_WATCHDOG_ENABLED or LOCAL_WATCHDOG_ENABLED:
            self._ensure_watchdog_process()
            self._watchdog_process.start()

        self._started = True


    def stop(self):
        if self._watchdog_process is not None:
            self._watchdog_process.stop()

        if self._local_watchdog_feeder is not None:
            self._local_watchdog_feeder.stop()

        # 配置热更新后的 restart 必须按最新 runtime_config 重建 watchdog。
        self._watchdog_process = None
        self._local_watchdog_feeder = None
        self._started = False


    def get_watchdog_status_payload(self):
        watchdog_worker_pid = None
        watchdog_worker_alive = False
        if self._watchdog_process is not None:
            watchdog_worker_pid = self._watchdog_process.get_pid()
            watchdog_worker_alive = self._watchdog_process.is_alive()

        local_feeder_thread_alive = False
        local_feeder_thread_name = None
        if self._local_watchdog_feeder is not None:
            local_feeder_thread_alive = self._local_watchdog_feeder.is_alive()
            local_feeder_thread_name = self._local_watchdog_feeder.get_thread_name()

        return {
            'client_id': self.client_id,
            'main_pid': os.getpid(),
            # Remote and local modes share one worker; report its state once.
            'watchdog_pid': watchdog_worker_pid,
            'watchdog_alive': watchdog_worker_alive,
            'remote_enabled': REMOTE_HTTP_WATCHDOG_ENABLED,
            'remote_control_url': self._build_remote_http_control_url(),
            'remote_interval_s': REMOTE_HTTP_WATCHDOG_INTERVAL_SECONDS,
            'remote_log': self._build_remote_watchdog_log_file_path(),
            'local_enabled': LOCAL_WATCHDOG_ENABLED,
            'local_heartbeat_interval_s': LOCAL_WATCHDOG_HEARTBEAT_INTERVAL_SECONDS,
            'local_timeout_s': LOCAL_WATCHDOG_TIMEOUT_SECONDS,
            'local_heartbeat_file': self._build_local_watchdog_heartbeat_file_path(),
            'local_log': self._build_local_watchdog_log_file_path(),
            'local_feeder_thread': local_feeder_thread_name,
            'local_feeder_alive': local_feeder_thread_alive,
        }