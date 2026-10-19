import sys

from client.runtime.client_util import reset, spawn_new_instance, reexec_restart
from core.utils.decorator import desc, confirm


class CommandSessionMixin:
    """
    会话生命周期命令。
    """

    @desc('Terminate current session', group='session')
    # @confirm('Terminate this Client session and close its connection?')
    def kill_connection(self):
        manager = getattr(self.socket, 'process_watchdog_manager', None)
        if manager is not None:
            manager.stop()
        self.socket.close()
        sys.exit(0)

    @desc('Restart client process and reconnect', group='session')
    @confirm('Restart this Client process and reconnect to the Server?')
    def reset(self):
        reset(self.socket)

    @desc('Restart current process by exec replacement', group='session')
    def reexec(self):
        reexec_restart(self.socket)

    @desc('Start a new client instance without exiting current process', group='session')
    def spawn_instance(self):
        process = spawn_new_instance()
        return 1, f'New client instance started, pid={process.pid}'
