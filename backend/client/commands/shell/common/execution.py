import os
import subprocess
import time

from client.commands.runtime.interrupts import cancel_policy
from client.commands.shell.decorators import shell_command
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.execution.python_execution.factory import get_python_execution_mode
from core.command_completion.models import CompletionSpec


@shell_command('Change working directory', group='shell', completion=CompletionSpec('filesystem', ('directory',)))
def cd(self, path):
    try:
        self._checkpoint()
        if not path.strip():
            return 1, os.getcwd()
        os.chdir(path)
        return 1, ''
    except CommandCancelledError:
        return 0, 'Command cancelled'
    except CommandTimeoutError:
        return 0, 'Command timed out'
    except OSError as exc:
        return 0, f'Failed to change directory: {exc}'
@shell_command('Run a shell command', group='execution', platforms=('mac', 'win', 'linux'))
@cancel_policy('process')
def shell(self, command):
    try:
        result = self.process_execution_service.run_shell_command(command)
        if result.returncode == 0:
            return 1, result.stdout
        details = [part.strip() for part in (result.stdout, result.stderr) if part and part.strip()]
        details.append(f'Command exited with code {result.returncode}')
        return 0, '\n'.join(details)
    except CommandCancelledError:
        return 0, 'Command cancelled'
    except (CommandTimeoutError, subprocess.TimeoutExpired):
        return 0, 'Command timed out'
    except Exception as e:
        return 0, f'Failed to execute command: {e}'
@shell_command('Run a shell command as a detached background process', group='execution', platforms=('mac', 'win', 'linux'))
def shell_bg(self, command):
    command_text = (command or '').strip()
    if not command_text:
        return 0, 'Usage: shell_bg <command ...>'

    try:
        self._checkpoint()
        process = self.process_execution_service.spawn_background_shell(command_text)
        return 1, (
            f'Background process started\n'
            f'PID: {process.pid}\n'
            f'Command: {command_text}'
        )
    except CommandCancelledError:
        return 0, 'Command cancelled'
    except CommandTimeoutError:
        return 0, 'Command timed out'
    except Exception as e:
        return 0, f'Failed to start background process: {e}'
@shell_command('Launch a program directly as a detached background process', group='execution', platforms=('mac', 'win', 'linux'))
def run_bg(self, command):
    command_text = (command or '').strip()
    if not command_text:
        return 0, 'Usage: run_bg <program> [args...]'

    try:
        self._checkpoint()
        process = self.process_execution_service.spawn_background_program(command_text)
        return 1, (
            f'Background program started\n'
            f'PID: {process.pid}\n'
            f'Command: {command_text}'
        )
    except CommandCancelledError:
        return 0, 'Command cancelled'
    except CommandTimeoutError:
        return 0, 'Command timed out'
    except Exception as e:
        return 0, f'Failed to start background program: {e}'
@shell_command('Run a command with live output', group='execution', output='stream', platforms=('mac', 'win', 'linux'))
@cancel_policy('process')
def shell_stream(self, command):
    try:
        service = self.process_execution_service
        process = service.start_stream_process(command)
        service.start_output_threads(process, timeout=self.DEFAULT_STREAM_TIMEOUT)
        service.wait_stream_process(process)
        time.sleep(0.1)

        if process.returncode == 0:
            self.emit_completed(status='success', message="Command completed")
        else:
            self.emit_completed(status='error', message=f'Command exited with code {process.returncode}')
    except CommandCancelledError:
        self.emit_completed(status='cancelled', message='Command cancelled')
    except (CommandTimeoutError, subprocess.TimeoutExpired):
        self.emit_completed(status='timed_out', message='Command timed out')
    except Exception as e:
        self.emit_completed(status='error', message=f'Failed to execute command: {e}')
@shell_command('Execute Python code and collect output', group='execution')
@cancel_policy('cooperative')
def pyexec(self, code, kwargs=None):
    try:
        return self.python_execution_service.execute(
            code,
            kwargs=kwargs,
            mode=get_python_execution_mode(),
            default_mode='inproc',
        )
    except CommandCancelledError as exc:
        return 0, (getattr(exc, 'output', '') + '\nCommand cancelled').lstrip('\n')
    except (CommandTimeoutError, subprocess.TimeoutExpired) as exc:
        return 0, (getattr(exc, 'output', '') + '\nCommand timed out').lstrip('\n')
    except Exception as e:
        return 0, f'Failed to execute code: {e}'
@shell_command('Execute Python code with streaming output', group='execution', output='stream')
@cancel_policy('cooperative')
def pyexec_stream(self, code, kwargs=None):
    try:
        return self.python_execution_service.execute(
            code,
            kwargs=kwargs,
            mode=get_python_execution_mode(),
            default_mode='inproc',
            stream=True,
        )
    except CommandCancelledError as exc:
        return 0, (getattr(exc, 'output', '') + '\nCommand cancelled').lstrip('\n')
    except (CommandTimeoutError, subprocess.TimeoutExpired) as exc:
        return 0, (getattr(exc, 'output', '') + '\nCommand timed out').lstrip('\n')
    except Exception as e:
        return 0, f'Failed to execute code: {e}'
