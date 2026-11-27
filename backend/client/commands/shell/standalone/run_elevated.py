"""Execute a requested command through the native authorization prompt."""

import subprocess

from client.commands.runtime.interrupts import cancel_policy, timeout
from client.commands.shell.decorators import shell_command
from client.commands.shell.standalone._elevated_mac import MacElevation
from client.commands.shell.standalone._elevated_process import (
    ELEVATED_COMMAND_TIMEOUT,
    ElevationCancelled,
)
from client.commands.shell.standalone._elevated_win import WindowsElevation
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.execution.command_confirmation import confirm
from core.utils.parsing import split_shell_arguments


_MODES = {
    '--shell': 'shell',
    '--collect': 'collect',
    '--detached': 'detached',
    '--open': 'open',
    '--show-console': 'show_console',
}
_ADAPTERS = {'mac': MacElevation, 'win': WindowsElevation}
_WINDOWS_MODES = {'--open', '--show-console'}


@shell_command('Run a command with elevated privileges', group='privilege', output='stream',
               platforms=('mac', 'win'))
@timeout(ELEVATED_COMMAND_TIMEOUT)
@cancel_policy('cooperative')
@confirm('This may show an operating system permission prompt and wait for authorization. Continue?',
         platform_messages={'win': 'This may show a Windows UAC permission prompt and wait for authorization. Continue?'},
         separator_options=_MODES)
def run_elevated(self, command):
    platform = self.command_platform
    tokens = command.split(maxsplit=1)
    option = tokens[0] if tokens else ''
    if option.startswith('--') and option != '--' and option not in _MODES:
        return 0, f'Unknown run_elevated option: {option}'
    mode = _MODES.get(option, 'shell')
    if option in _MODES:
        command = tokens[1] if len(tokens) > 1 else ''
        tokens = command.split(maxsplit=1)
        if tokens and tokens[0] in _MODES:
            return 0, f'Choose only one mode: {", ".join(_MODES)}'
    if tokens and tokens[0] == '--':
        command = tokens[1] if len(tokens) > 1 else ''
    if option in _WINDOWS_MODES and platform != 'win':
        return 0, f'run_elevated {option} is only available on Windows'
    if not command.strip():
        options = [flag for flag in _MODES if platform == 'win' or flag not in _WINDOWS_MODES]
        return 0, f'Usage: run_elevated [{" | ".join(options)}] [--] <command>'
    try:
        self._checkpoint()
        if mode in ('detached', 'open'):
            command = split_shell_arguments(command, literal_backslashes=(platform == 'win'))
        adapter = _ADAPTERS[platform](self)
        return getattr(adapter, mode)(command)
    except ElevationCancelled as exc:
        self.emit_completed(status='cancelled', message=str(exc))
    except CommandCancelledError:
        self.emit_completed(status='cancelled', message='Elevated command cancelled')
    except (CommandTimeoutError, subprocess.TimeoutExpired):
        self.emit_completed(status='timed_out', message='Elevated command timed out')
    except (OSError, ValueError, IndexError) as exc:
        return 0, f'Could not run elevated command: {exc}'
