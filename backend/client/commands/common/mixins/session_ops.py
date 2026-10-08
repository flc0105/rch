import sys

from client.commands.runtime.interrupts import interruptible
from client.runtime.client_util import reset, spawn_new_instance, reexec_restart
from core.utils.decorator import desc


class CommandSessionMixin:
    """
    会话生命周期命令。
    """

    @desc('Terminate current session', group='session')
    @interruptible()
    def kill_connection(self):
        self.socket.close()
        sys.exit(0)

    @desc('Restart client process and reconnect', group='session')
    @interruptible()
    def reset(self):
        reset(self.socket)

    @desc('Restart current process by exec replacement', group='session')
    @interruptible()
    def reexec(self):
        reexec_restart(self.socket)

    @desc('Start a new client instance without exiting current process', group='session')
    @interruptible()
    def spawn_instance(self):
        process = spawn_new_instance()
        return 1, f'New client instance started, pid={process.pid}'
