import sys

from client.runtime.client_util import reset, spawn_new_instance, reexec_restart
from client.commands.runtime.command_variable_resolver import CommandVariableResolutionError
from core.utils.decorator import desc, confirm


class CommandSessionMixin:
    """
    会话生命周期命令。
    """

    @desc('Manage variables for this Client connection', group='session')
    def var(self, arg=''):
        resolver = self._command_runtime.command_variable_resolver
        text = str(arg or '').strip()
        if not text:
            variables = resolver.list_vars()
            return 1, '\n'.join(f'{name}={value}' for name, value in variables.items()) or 'No user variables'
        if text.startswith('--unset '):
            name = text[len('--unset '):].strip()
            if not resolver.USER_NAME_PATTERN.fullmatch(name):
                return 0, 'Usage: var --unset NAME'
            return (1, f'{name} removed') if resolver.unset_var(name) else (0, f'User variable is not set: {name}')
        if '=' not in text:
            return 0, 'Usage: var NAME=VALUE | var --unset NAME | var'
        name, value = text.split('=', 1)
        if name != name.strip() or (value and value[0].isspace()):
            return 0, 'Usage: var NAME=VALUE (no spaces around =)'
        try:
            resolver.set_var(name, value)
        except CommandVariableResolutionError as exc:
            return 0, str(exc)
        return 1, f'{name} set'

    @desc('Terminate current session', group='session')
    # @confirm('Terminate this Client session and close its connection?')
    def kill_instance(self):
        self.socket.report_session_end('client_exit', command='kill_instance')
        manager = getattr(self.socket, 'process_watchdog_manager', None)
        if manager is not None:
            manager.stop()
        self.socket.close()
        sys.exit(0)

    @desc('Pause this Client instance connection until Remote Watchdog resume', group='session')
    def pause_instance(self):
        lifecycle = getattr(self.socket, 'connection_lifecycle', None)
        if lifecycle is None or not lifecycle.request_pause_after_result():
            return 0, 'Remote Watchdog is not available for this Client instance'
        return 1, 'Pause requested. The Client will disconnect after this command completes; its process and Remote Watchdog will remain running.'

    @desc('Restart client process and reconnect', group='session')
    @confirm('Restart this Client process and reconnect to the Server?')
    def relaunch_instance(self, options=''):
        if str(options or '').strip():
            return 0, 'Usage: relaunch_instance [--no-confirm]'
        reset(self.socket)

    @desc('Restart current process by exec replacement', group='session')
    def reexec_instance(self):
        reexec_restart(self.socket)

    @desc('Start a new client instance without exiting current process', group='session')
    def spawn_instance(self):
        process = spawn_new_instance()
        return 1, f'New client instance started, pid={process.pid}'
