"""Read idle time using the selected desktop platform's existing system API."""
from client.commands.runtime.interrupts import timeout
from client.commands.shell.decorators import shell_command
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


@shell_command('Get user idle time', group='system', platforms=('mac', 'win'))
@timeout({'win': 10})
def idletime(self):
    collect = {'mac': _idletime_mac, 'win': _idletime_win}
    return collect[self.command_platform](self)


def _idletime_mac(owner):
    try:
        from Quartz import (
            CGEventSourceSecondsSinceLastEventType,
            kCGAnyInputEventType,
            kCGEventSourceStateHIDSystemState,
        )

        idle_seconds = owner._run_checked(
            CGEventSourceSecondsSinceLastEventType,
            kCGEventSourceStateHIDSystemState,
            kCGAnyInputEventType,
        )
        return 1, f'User idle time: {idle_seconds:.2f} seconds'
    except CommandCancelledError:
        return 0, 'Command cancelled'
    except CommandTimeoutError:
        return 0, 'Command timed out and was terminated'
    except Exception as e:
        return 0, f'Failed to read idle time: {e}'


def _idletime_win(_owner):
    try:
        import win32api

        idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
        idle_seconds = idle_ms / 1000.0

        return 1, f'User idle time: {idle_seconds:.2f} seconds'

    except Exception as e:
        return 0, f'Failed to get idle time: {e}'
