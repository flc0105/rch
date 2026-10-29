import json
import logging
import os
import threading
import time


def _build_local_heartbeat_watchdog_file_logger(log_file_path: str):
    logger_name = f'local_heartbeat_watchdog_file_logger::{os.path.abspath(log_file_path)}'
    file_logger = logging.getLogger(logger_name)
    file_logger.setLevel(logging.INFO)
    file_logger.propagate = False

    if not file_logger.handlers:
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_logger.addHandler(file_handler)

    return file_logger


class LocalHeartbeatWatchdogFeeder:
    def __init__(
        self,
        client_id: str,
        heartbeat_interval_seconds: float,
        heartbeat_file_path: str,
        local_heartbeat_watchdog_log_file_path: str,
    ):
        self.client_id = str(client_id or '').strip()
        self.heartbeat_interval_seconds = max(float(heartbeat_interval_seconds or 0), 0.5)
        self.heartbeat_file_path = str(heartbeat_file_path or '').strip()
        self.local_heartbeat_watchdog_log_file_path = str(local_heartbeat_watchdog_log_file_path or '').strip()

        self._stop_event = threading.Event()
        self._thread = None
        self._local_logger = _build_local_heartbeat_watchdog_file_logger(self.local_heartbeat_watchdog_log_file_path)


    def _write_heartbeat(self):
        temp_file_path = f'{self.heartbeat_file_path}.tmp'

        os.makedirs(os.path.dirname(self.heartbeat_file_path), exist_ok=True)
        payload = {
            'ts': time.time(),
            'pid': os.getpid(),
            'client_id': self.client_id,
        }

        with open(temp_file_path, 'w', encoding='utf-8') as file_obj:
            json.dump(payload, file_obj)

        os.replace(temp_file_path, self.heartbeat_file_path)


    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self._write_heartbeat()
            except Exception as e:
                self._local_logger.error(f'write Local Heartbeat Watchdog heartbeat failed: {e}')

            self._stop_event.wait(self.heartbeat_interval_seconds)


    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._write_heartbeat()

        self._thread = threading.Thread(
            target=self._run_loop,
            name='LocalHeartbeatWatchdogFeeder',
            daemon=True,
        )
        self._thread.start()


    def stop(self):
        self._stop_event.set()


    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


    def get_thread_name(self):
        if self._thread is None:
            return None
        return self._thread.name


class LocalHeartbeatWatchdogActionExecutor:
    def __init__(self, restart_parent_callback):
        self.restart_parent_callback = restart_parent_callback


    def restart_parent(self):
        self.restart_parent_callback()


class LocalHeartbeatWatchdogMonitor:
    def __init__(
        self,
        client_id: str,
        heartbeat_file_path: str,
        timeout_seconds: float,
        local_heartbeat_watchdog_log_file_path: str,
        action_executor: LocalHeartbeatWatchdogActionExecutor,
    ):
        self.client_id = str(client_id or '').strip()
        self.heartbeat_file_path = str(heartbeat_file_path or '').strip()
        self.timeout_seconds = max(float(timeout_seconds or 0), 1.0)
        self.local_heartbeat_watchdog_log_file_path = str(local_heartbeat_watchdog_log_file_path or '').strip()
        self.action_executor = action_executor

        self._local_logger = _build_local_heartbeat_watchdog_file_logger(self.local_heartbeat_watchdog_log_file_path)
        self._timeout_triggered = False


    def _read_heartbeat_age_seconds(self):
        if not self.heartbeat_file_path or not os.path.isfile(self.heartbeat_file_path):
            return None

        with open(self.heartbeat_file_path, 'r', encoding='utf-8') as file_obj:
            data = json.load(file_obj)

        ts_value = float(data.get('ts') or 0)
        if ts_value <= 0:
            return None

        return max(time.time() - ts_value, 0.0)


    def run_iteration(self):
        try:
            heartbeat_age_seconds = self._read_heartbeat_age_seconds()
            if heartbeat_age_seconds is None:
                return

            if heartbeat_age_seconds <= self.timeout_seconds:
                self._timeout_triggered = False
                return

            if self._timeout_triggered:
                return

            self._timeout_triggered = True
            self._local_logger.warning(
                f'Local Heartbeat Watchdog timeout detected: client_id={self.client_id}, '
                f'heartbeat_age_seconds={heartbeat_age_seconds:.2f}, '
                f'timeout_seconds={self.timeout_seconds}'
            )
            self._local_logger.warning(
                f'Local Heartbeat Watchdog restart requested: client_id={self.client_id}'
            )
            self.action_executor.restart_parent()
        except Exception as e:
            self._local_logger.error(f'Local Heartbeat Watchdog monitor failed: {e}')