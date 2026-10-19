import json
import os
import subprocess
import sys
import time

from client.watchdog.remote_watchdog import (
    RemoteHttpWatchdogMonitor,
    WatchdogActionExecutor,
)
from client.watchdog.local_watchdog import (
    LocalWatchdogActionExecutor,
    LocalWatchdogMonitor,
)
from client.watchdog.recovery_source import LOCAL_WATCHDOG


class ClientWatchdogWorker:
    def __init__(
        self,
        parent_pid: int,
        client_id: str,
        launch_cwd: str,
        parent_launch_argv: list[str],
        remote_http_watchdog_enabled: bool,
        remote_http_watchdog_base_url: str,
        remote_http_watchdog_interval_seconds: float,
        remote_watchdog_log_file_path: str,
        local_watchdog_enabled: bool,
        local_watchdog_timeout_seconds: float,
        local_watchdog_heartbeat_file_path: str,
        local_watchdog_log_file_path: str,
    ):
        self.parent_pid = int(parent_pid)
        self.client_id = str(client_id or '').strip()

        self._action_executor = WatchdogActionExecutor(
            parent_pid=parent_pid,
            launch_cwd=launch_cwd,
            parent_launch_argv=parent_launch_argv,
        )

        self._remote_monitor = None
        if remote_http_watchdog_enabled:
            self._remote_monitor = RemoteHttpWatchdogMonitor(
                client_id=client_id,
                base_url=remote_http_watchdog_base_url,
                poll_interval=remote_http_watchdog_interval_seconds,
                remote_watchdog_log_file_path=remote_watchdog_log_file_path,
                action_executor=self._action_executor,
            )

        self._local_monitor = None
        if local_watchdog_enabled:
            self._local_monitor = LocalWatchdogMonitor(
                client_id=client_id,
                heartbeat_file_path=local_watchdog_heartbeat_file_path,
                timeout_seconds=local_watchdog_timeout_seconds,
                local_watchdog_log_file_path=local_watchdog_log_file_path,
                action_executor=LocalWatchdogActionExecutor(
                    lambda: self._action_executor.restart_parent_and_exit(recovery_source=LOCAL_WATCHDOG)
                ),
            )


    def run(self):
        while True:
            if not self._action_executor.is_parent_alive():
                break

            now = time.time()

            if self._remote_monitor is not None:
                self._remote_monitor.run_iteration(now)

            if self._local_monitor is not None:
                self._local_monitor.run_iteration()

            time.sleep(0.5)


class ClientWatchdogProcess:
    def __init__(
        self,
        client_id: str,
        remote_http_watchdog_enabled: bool,
        remote_http_watchdog_base_url: str,
        remote_http_watchdog_interval_seconds: float,
        remote_watchdog_log_file_path: str,
        local_watchdog_enabled: bool,
        local_watchdog_timeout_seconds: float,
        local_watchdog_heartbeat_file_path: str,
        local_watchdog_log_file_path: str,
    ):
        self.client_id = str(client_id or '').strip()
        self.remote_http_watchdog_enabled = bool(remote_http_watchdog_enabled)
        self.remote_http_watchdog_base_url = str(remote_http_watchdog_base_url or '').rstrip('/')
        self.remote_http_watchdog_interval_seconds = max(float(remote_http_watchdog_interval_seconds or 0), 1.0)
        self.remote_watchdog_log_file_path = str(remote_watchdog_log_file_path or '').strip()
        self.local_watchdog_enabled = bool(local_watchdog_enabled)
        self.local_watchdog_timeout_seconds = max(float(local_watchdog_timeout_seconds or 0), 1.0)
        self.local_watchdog_heartbeat_file_path = str(local_watchdog_heartbeat_file_path or '').strip()
        self.local_watchdog_log_file_path = str(local_watchdog_log_file_path or '').strip()
        self._process = None


    def _build_parent_launch_argv(self):
        if getattr(sys, 'frozen', False):
            return [os.path.realpath(sys.executable), *sys.argv[1:]]

        return [os.path.realpath(sys.executable), os.path.realpath(sys.argv[0]), *sys.argv[1:]]


    def _build_worker_argv(self):
        parent_launch_argv_json = json.dumps(self._build_parent_launch_argv())

        if getattr(sys, 'frozen', False):
            return [
                os.path.realpath(sys.executable),
                '--watchdog-worker',
                '--watch-parent-pid', str(os.getpid()),
                '--watch-client-id', self.client_id,
                '--watch-launch-cwd', os.getcwd(),
                '--watch-parent-launch-argv-json', parent_launch_argv_json,
                '--watch-remote-http-watchdog-enabled', '1' if self.remote_http_watchdog_enabled else '0',
                '--watch-remote-http-watchdog-base-url', self.remote_http_watchdog_base_url,
                '--watch-remote-http-watchdog-interval-seconds', str(self.remote_http_watchdog_interval_seconds),
                '--watch-remote-watchdog-log-file-path', self.remote_watchdog_log_file_path,
                '--watch-local-watchdog-enabled', '1' if self.local_watchdog_enabled else '0',
                '--watch-local-watchdog-timeout-seconds', str(self.local_watchdog_timeout_seconds),
                '--watch-local-watchdog-heartbeat-file-path', self.local_watchdog_heartbeat_file_path,
                '--watch-local-watchdog-log-file-path', self.local_watchdog_log_file_path,
            ]

        return [
            os.path.realpath(sys.executable),
            os.path.realpath(sys.argv[0]),
            '--watchdog-worker',
            '--watch-parent-pid', str(os.getpid()),
            '--watch-client-id', self.client_id,
            '--watch-launch-cwd', os.getcwd(),
            '--watch-parent-launch-argv-json', parent_launch_argv_json,
            '--watch-remote-http-watchdog-enabled', '1' if self.remote_http_watchdog_enabled else '0',
            '--watch-remote-http-watchdog-base-url', self.remote_http_watchdog_base_url,
            '--watch-remote-http-watchdog-interval-seconds', str(self.remote_http_watchdog_interval_seconds),
            '--watch-remote-watchdog-log-file-path', self.remote_watchdog_log_file_path,
            '--watch-local-watchdog-enabled', '1' if self.local_watchdog_enabled else '0',
            '--watch-local-watchdog-timeout-seconds', str(self.local_watchdog_timeout_seconds),
            '--watch-local-watchdog-heartbeat-file-path', self.local_watchdog_heartbeat_file_path,
            '--watch-local-watchdog-log-file-path', self.local_watchdog_log_file_path,
        ]


    def start(self):
        if self._process is not None and self._process.poll() is None:
            return

        popen_kwargs = {
            'cwd': os.getcwd(),
            'env': dict(os.environ),
            'stdin': subprocess.DEVNULL,
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'close_fds': True,
        }

        if os.name == 'nt':
            creationflags = 0
            creationflags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            creationflags |= getattr(subprocess, 'DETACHED_PROCESS', 0)
            self._process = subprocess.Popen(
                self._build_worker_argv(),
                shell=False,
                creationflags=creationflags,
                **popen_kwargs,
            )
        elif os.name == 'posix':
            self._process = subprocess.Popen(
                self._build_worker_argv(),
                shell=False,
                start_new_session=True,
                **popen_kwargs,
            )
        else:
            raise RuntimeError(f'Unsupported os.name: {os.name}')


    def stop(self):
        process = self._process
        if process is None:
            return

        if process.poll() is not None:
            return

        try:
            if os.name == 'nt':
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/F', '/T'],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.kill(process.pid, 9)
        except Exception:
            pass


    def get_pid(self):
        if self._process is None:
            return None
        return self._process.pid


    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None



def _read_flag_value(flag_name: str, default_value=None):
    argv = sys.argv[1:]
    for index, arg in enumerate(argv):
        if arg == flag_name and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(f'{flag_name}='):
            return arg.split('=', 1)[1]
    return default_value



def run_watchdog_worker_from_argv():
    parent_pid = int(_read_flag_value('--watch-parent-pid', '0') or '0')
    client_id = _read_flag_value('--watch-client-id', '') or ''
    launch_cwd = _read_flag_value('--watch-launch-cwd', os.getcwd()) or os.getcwd()
    parent_launch_argv_json = _read_flag_value('--watch-parent-launch-argv-json', '[]') or '[]'

    remote_http_watchdog_enabled = (_read_flag_value('--watch-remote-http-watchdog-enabled', '1') or '1') == '1'
    remote_http_watchdog_base_url = _read_flag_value('--watch-remote-http-watchdog-base-url', '') or ''
    remote_http_watchdog_interval_seconds = float(
        _read_flag_value('--watch-remote-http-watchdog-interval-seconds', '30') or '30'
    )
    remote_watchdog_log_file_path = _read_flag_value('--watch-remote-watchdog-log-file-path', '') or ''

    local_watchdog_enabled = (_read_flag_value('--watch-local-watchdog-enabled', '1') or '1') == '1'
    local_watchdog_timeout_seconds = float(
        _read_flag_value('--watch-local-watchdog-timeout-seconds', '15') or '15'
    )
    local_watchdog_heartbeat_file_path = _read_flag_value('--watch-local-watchdog-heartbeat-file-path', '') or ''
    local_watchdog_log_file_path = _read_flag_value('--watch-local-watchdog-log-file-path', '') or ''

    parent_launch_argv = json.loads(parent_launch_argv_json)
    if not isinstance(parent_launch_argv, list):
        raise ValueError('Invalid parent launch argv json')

    worker = ClientWatchdogWorker(
        parent_pid=parent_pid,
        client_id=client_id,
        launch_cwd=launch_cwd,
        parent_launch_argv=parent_launch_argv,
        remote_http_watchdog_enabled=remote_http_watchdog_enabled,
        remote_http_watchdog_base_url=remote_http_watchdog_base_url,
        remote_http_watchdog_interval_seconds=remote_http_watchdog_interval_seconds,
        remote_watchdog_log_file_path=remote_watchdog_log_file_path,
        local_watchdog_enabled=local_watchdog_enabled,
        local_watchdog_timeout_seconds=local_watchdog_timeout_seconds,
        local_watchdog_heartbeat_file_path=local_watchdog_heartbeat_file_path,
        local_watchdog_log_file_path=local_watchdog_log_file_path,
    )
    worker.run()