"""Shared watchdog process actions, independent of local/remote monitors."""

import os
import signal
import subprocess
import time
from client.runtime.client_util import is_process_alive
from client.watchdog.watchdog_environment import without_process_watchdog_environment
from client.watchdog.recovery_source import RECOVERY_SOURCE_ENV
from client.runtime.launch_context import detached_launch_environment

class WatchdogActionExecutor:
    def __init__(self, parent_pid: int, launch_cwd: str, parent_launch_argv: list[str]):
        self.parent_pid = int(parent_pid)
        self.launch_cwd = str(launch_cwd or '').strip() or os.getcwd()
        self.parent_launch_argv = list(parent_launch_argv or [])

    def is_parent_alive(self) -> bool:
        return is_process_alive(self.parent_pid)


    def kill_parent_process(self):
        if not self.is_parent_alive():
            return

        if os.name == 'nt':
            subprocess.run(
                ['taskkill', '/PID', str(self.parent_pid), '/F', '/T'],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(self.parent_pid, signal.SIGKILL)


    def spawn_restarted_parent(self, *, recovery_source=''):
        if not self.parent_launch_argv:
            raise RuntimeError('Missing parent launch argv')

        env = detached_launch_environment(without_process_watchdog_environment())
        if recovery_source:
            env[RECOVERY_SOURCE_ENV] = recovery_source
        popen_kwargs = {
            'cwd': self.launch_cwd,
            'env': env,
            'stdin': subprocess.DEVNULL,
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'close_fds': True,
        }

        if os.name == 'nt':
            creationflags = 0
            creationflags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            creationflags |= getattr(subprocess, 'DETACHED_PROCESS', 0)
            subprocess.Popen(
                self.parent_launch_argv,
                shell=False,
                creationflags=creationflags,
                **popen_kwargs,
            )
        elif os.name == 'posix':
            subprocess.Popen(
                self.parent_launch_argv,
                shell=False,
                start_new_session=True,
                **popen_kwargs,
            )
        else:
            raise RuntimeError(f'Unsupported os.name: {os.name}')


    def restart_parent_and_exit(self, *, recovery_source=''):
        if recovery_source:
            self.spawn_restarted_parent(recovery_source=recovery_source)
        else:
            self.spawn_restarted_parent()
        time.sleep(0.2)
        from client.watchdog.watchdog_environment import PROCESS_WATCHDOG_SESSION_ENV
        if os.environ.get(PROCESS_WATCHDOG_SESSION_ENV):
            from client.watchdog.process_watchdog import stop_process_watchdog_from_environment
            stop_process_watchdog_from_environment()
        self.kill_parent_process()
        os._exit(0)


    def kill_parent_and_exit(self):
        from client.watchdog.watchdog_environment import PROCESS_WATCHDOG_SESSION_ENV
        if os.environ.get(PROCESS_WATCHDOG_SESSION_ENV):
            from client.watchdog.process_watchdog import stop_process_watchdog_from_environment
            stop_process_watchdog_from_environment()
        self.kill_parent_process()
        os._exit(0)

    def spawn_new_instance(self):
        self.spawn_restarted_parent()


