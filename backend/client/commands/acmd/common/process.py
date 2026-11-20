"""Common ACMD process command registrations."""

import math
import time

from client.commands.acmd.decorators import argument_command
from client.commands.runtime.interrupts import cancel_policy
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.external_tools.processes import is_pid_alive
from client.commands.acmd.standalone.ps import ps as ps_command
from client.commands.acmd.standalone.kill import kill as kill_command


WAIT_PID_SPEC = ArgumentCommandSpec(
    name='wait_pid',
    description='Wait for a process to exit',
    options=[
        ArgumentOptionSpec('pid', 'int', required=True, positional_index=0, help_text='Process ID'),
        ArgumentOptionSpec('timeout', 'float', default=30, help_text='Maximum wait in seconds (default: 30)'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd wait_pid 1234', 'acmd wait_pid --pid 1234 --timeout 10'],
)


class ACMDProcessCommands:
    ps = ps_command
    kill = kill_command

    @argument_command('wait_pid', spec=WAIT_PID_SPEC)
    @cancel_policy('cooperative')
    def wait_pid(self, args_dict):
        self._set_cancel_policy('cooperative')
        self._checkpoint()
        pid = args_dict['pid']
        timeout = args_dict['timeout']
        if not 0 < pid <= 0x7fffffff:
            return 0, '--pid must be a positive process ID'
        if not math.isfinite(timeout) or timeout <= 0:
            return 0, '--timeout must be a positive number of seconds'

        process = None
        if self.command_platform != 'ios':
            try:
                import psutil
            except ImportError:
                pass
            else:
                try:
                    process = psutil.Process(pid)
                except psutil.NoSuchProcess:
                    return 1, f'PID {pid} is no longer running.'
                except psutil.AccessDenied:
                    pass

        deadline = time.monotonic() + timeout
        while True:
            self._checkpoint()
            if process is None:
                running = is_pid_alive(pid)
            else:
                try:
                    running = process.is_running() and process.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD)
                except psutil.NoSuchProcess:
                    running = False
                except psutil.AccessDenied:
                    running = is_pid_alive(pid)
            if not running:
                return 1, f'PID {pid} is no longer running.'
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 0, f'Timed out waiting for PID {pid} to exit.'
            time.sleep(min(0.2, remaining))
