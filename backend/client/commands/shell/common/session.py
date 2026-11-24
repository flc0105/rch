import os
import subprocess
import sys
import threading

from client.runtime.client_util import get_executable_argv, get_runtime_root
from client.runtime.command_variable_resolver import CommandVariableResolutionError
from core.utils.decorator import confirm
from client.commands.shell.decorators import shell_command, reverse_only


@shell_command('Manage variables for this Client connection', group='session')
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
@shell_command('Pause this Client connection without terminating its process', group='session')
def pause_connection(self):
    self.socket.request_pause()
    return 1, 'Client connection will pause after this result is sent'
@shell_command('Terminate current session', group='session')
# @confirm('Terminate this Client session and close its connection?')
def kill_instance(self):
    self.socket.report_session_end('server_requested_disconnect', command='kill_instance')
    watchdog_manager = getattr(self.socket, 'watchdog_manager', None)
    if watchdog_manager is not None:
        watchdog_manager.stop()
    manager = getattr(self.socket, 'process_recovery_watchdog_manager', None)
    if manager is not None:
        manager.stop()
    self.socket.close()
    sys.exit(0)
@shell_command('Restart client process and reconnect', group='session', platforms=('mac', 'win', 'linux'))
@reverse_only('Restart Instance is not supported in Bind mode. Use Reconnect to reopen the connection.')
@confirm('Restart this Client process and reconnect to the Server?')
def relaunch_instance(self, options=''):
    if str(options or '').strip():
        return 0, 'Usage: relaunch_instance [--no-confirm]'
    _relaunch_instance(self.socket)
@shell_command('Restart current process by exec replacement', group='session', platforms=('mac', 'linux'))
def reexec_instance(self):
    _reexec_instance(self.socket)
@shell_command('Start a new client instance without exiting current process', group='session', platforms=('mac', 'win', 'linux'))
@reverse_only('Duplicate Instance is not supported in Bind mode. Use a different profile and port to start a separate instance.')
def spawn_instance(self):
    process = _spawn_instance()
    # Duplicate 已是独立 session；父进程只负责异步回收退出状态，避免 zombie。
    if os.name == 'posix' and callable(getattr(process, 'wait', None)):
        threading.Thread(target=process.wait, name='rch-duplicate-reaper', daemon=True).start()
    return 1, f'New client instance started, pid={process.pid}'


def _relaunch_instance(socket):
    """Start a replacement Client, then end the current session."""
    _spawn_instance()
    socket.report_session_end('client_restart', command='relaunch_instance')

    manager = getattr(socket, 'process_recovery_watchdog_manager', None)
    if manager is not None:
        manager.stop()

    try:
        socket.close()
    except Exception:
        pass

    os._exit(0)


def _reexec_instance(socket):
    """Replace the current Client process while preserving its PID."""
    socket.report_session_end('client_restart', command='reexec_instance')

    try:
        socket.close()
    except Exception:
        pass

    launch_cwd = get_runtime_root()
    try:
        os.chdir(launch_cwd)
    except Exception:
        pass

    # Use argv directly: shell-formatted commands cannot be split safely.
    argv = get_executable_argv()
    os.execv(argv[0], argv)


def _spawn_instance(*, start_new_session=True, stderr_path=''):
    """Start a separate Client instance; relaunch and duplicate both use this."""
    restart_argv = get_executable_argv()
    launch_cwd = get_runtime_root()

    from client.watchdog.watchdog_environment import without_process_recovery_watchdog_environment

    stderr_file = open(stderr_path, 'ab') if stderr_path else None
    popen_kwargs = {
        'cwd': launch_cwd,
        'env': without_process_recovery_watchdog_environment(),
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': stderr_file or subprocess.DEVNULL,
        'close_fds': True,
    }

    try:
        if os.name == 'nt':
            flags = (getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                     | getattr(subprocess, 'DETACHED_PROCESS', 0))
            return subprocess.Popen(restart_argv, shell=False, creationflags=flags, **popen_kwargs)
        if os.name == 'posix':
            return subprocess.Popen(restart_argv, shell=False,
                                    start_new_session=start_new_session, **popen_kwargs)
        raise RuntimeError(f'Unsupported os.name: {os.name}')
    finally:
        if stderr_file is not None:
            stderr_file.close()
