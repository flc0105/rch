import ctypes
import json
import logging
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request

from client.runtime.client_util import spawn_new_instance, is_process_alive
from client.runtime.local_ipc import send_local_command
from client.watchdog.watchdog_environment import without_process_recovery_watchdog_environment
from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV
from client.runtime.launch_context import detached_launch_environment
from client.watchdog.watchdog_action import WatchdogActionExecutor

HTTP_CONTROL_COMMANDS = {'kill', 'relaunch', 'clone', 'resume'}

def _build_remote_control_watchdog_file_logger(log_file_path: str):
    logger_name = f'remote_control_watchdog_file_logger::{os.path.abspath(log_file_path)}'
    file_logger = logging.getLogger(logger_name)
    file_logger.setLevel(logging.DEBUG)
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


class RemoteControlWatchdogMonitor:
    def __init__(
        self,
        client_id: str,
        base_url: str,
        poll_interval: float,
        remote_control_watchdog_log_file_path: str,
        action_executor: WatchdogActionExecutor,
    ):
        self.client_id = str(client_id or '').strip()
        self.base_url = str(base_url or '').rstrip('/')
        self.poll_interval = max(float(poll_interval or 0), 1.0)
        self.remote_control_watchdog_log_file_path = str(remote_control_watchdog_log_file_path or '').strip()
        self.action_executor = action_executor

        self._logger = _build_remote_control_watchdog_file_logger(self.remote_control_watchdog_log_file_path)
        self._next_poll_at = 0.0


    def _build_poll_url(self) -> str:
        return f'{self.base_url}/api/connections/{self.client_id}/control'


    def _log_http_debug(self, message: str):
        self._logger.debug(message)


    def _log_http_warning(self, message: str):
        self._logger.warning(message)


    def _log_http_error(self, message: str):
        self._logger.error(message)


    def _fetch_command(self) -> dict:
        request = urllib.request.Request(self._build_poll_url(), method='GET', headers={'Accept': 'application/json'})

        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode('utf-8', errors='replace'))

        if not isinstance(payload, dict):
            return {}

        data = payload.get('data') or {}
        if not isinstance(data, dict):
            return {}

        command = str(data.get('command') or '').strip().lower()
        if command in HTTP_CONTROL_COMMANDS:
            return data

        return {}

    def _execute_command(self, command: str):
        command_text = str(command or '').strip().lower()

        if command_text == 'kill':
            self.action_executor.kill_parent_and_exit()
            return

        if command_text == 'relaunch':
            self.action_executor.restart_parent_and_exit()
            return

        if command_text == 'clone':
            self.action_executor.spawn_new_instance()
            return

        if command_text == 'resume':
            send_local_command('connection.resume')
            return

        raise ValueError(f'Unsupported remote HTTP control action: {command_text}')
   
    def _report_control_result(self, command_id: str, status: str, detail: str = ''):
        if not command_id:
            return
        body = json.dumps({'command_id': command_id, 'status': status, 'detail': detail}).encode('utf-8')
        request = urllib.request.Request(
            self._build_poll_url() + '/ack', data=body, method='POST',
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=5):
            pass

    def run_iteration(self, now: float):
        if now < self._next_poll_at:
            return
        self._next_poll_at = now + self.poll_interval

        poll_url = self._build_poll_url()
        self._log_http_debug(f'http control poll request: client_id={self.client_id}, url={poll_url}')
        try:
            payload = self._fetch_command()
            command = str(payload.get('command') or '').lower()
            if command:
                self._log_http_warning(f'http control command received: client_id={self.client_id}, command={command}')
                command_id = str(payload.get('command_id') or '')
                try:
                    self._execute_command(command)
                except Exception as exc:
                    if command in ('clone', 'resume'):
                        self._report_control_result(command_id, 'failed', str(exc))
                    raise
                else:
                    if command in ('clone', 'resume'):
                        # 'delivered' confirms IPC acknowledgement, not TCP reconnection.
                        self._report_control_result(command_id, 'delivered')
        except urllib.error.HTTPError as e:
            self._log_http_error(f'http control poll failed: client_id={self.client_id}, http_status={e.code}, url={poll_url}')
        except urllib.error.URLError as e:
            self._log_http_error(f'http control poll failed: client_id={self.client_id}, error={e}, url={poll_url}')
        except Exception as e:
            self._log_http_error(f'http control poll failed: client_id={self.client_id}, error={e}, url={poll_url}')
