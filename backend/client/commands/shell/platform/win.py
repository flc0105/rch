import subprocess

from client.commands.shell.decorators import shell_command
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


@shell_command('Run a program without waiting (detached)', group='execution')
def run(self, command):
    command_text = (command or '').strip()
    if not command_text:
        return 0, 'Usage: run <program ...>'

    try:
        # Windows: 创建新控制台窗口
        process = subprocess.Popen(
            command_text,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

        return 1, f'Process created: {process.pid}'

    except CommandCancelledError:
        return 0, 'Command cancelled'
    except CommandTimeoutError:
        return 0, 'Command timed out and was terminated'
    except Exception as e:
        return 0, f'Failed to start process: {e}'
