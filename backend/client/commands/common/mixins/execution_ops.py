from client.commands.runtime.interrupts import cancel_policy
import os
import subprocess
import time

from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.execution.python_execution.factory import (
    build_python_execution_strategy,
    get_python_execution_mode
)
from client.runtime.execution.process.process_execution_service import ProcessExecutionService
from client.config import runtime_config
from core.utils.decorator import desc


from client.runtime.execution.python_process import PythonProcessExecutionMixin


class CommandExecutionMixin(PythonProcessExecutionMixin):
    """User-facing shell and Python commands."""
    # ------------------ 基础执行命令 ------------------ #
    @desc('Change working directory', group='shell')
    def cd(self, path):
        try:
            if not path.strip():
                return 1, os.getcwd()
            os.chdir(path)
            return 1, ""
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to change directory: {e}'

    @desc('Run a shell command', group='execution')
    @cancel_policy('process')
    def shell(self, command):
        try:
            result = self._run_shell_command(command)
            if result.returncode == 0:
                return 1, result.stdout
            details = [part.strip() for part in (result.stdout, result.stderr) if part and part.strip()]
            details.append(f'Command exited with code {result.returncode}')
            return 0, '\n'.join(details)
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to execute command: {e}'

    @desc('Run a program in background', group='execution')
    def bgrun(self, command):
        """
        后台启动指定程序/命令，不等待其执行结束。
        """
        command_text = (command or '').strip()
        if not command_text:
            return 0, 'Usage: bgrun <program ...>'

        try:
            process = self._spawn_background_process(command_text)
            return 1, (
                f'Background process started\n'
                f'PID: {process.pid}\n'
                f'Command: {command_text}'
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to start background process: {e}'

    @desc('Start an independent program in a new session', group='execution')
    def run_detached(self, command):
        command_text = (command or '').strip()
        if not command_text:
            return 0, 'Usage: run_detached <program> [args...]'

        try:
            process = self._spawn_detached_program(command_text)
            return 1, (
                f'Detached process started\n'
                f'PID: {process.pid}\n'
                f'Command: {command_text}'
            )
        except Exception as e:
            return 0, f'Failed to start detached process: {e}'

    @desc('Run a command with live output', group='execution', output='stream')
    @cancel_policy('process')
    def shell_stream(self, command):
        try:
            process = self._start_stream_process(command)
            self._start_output_threads(process)
            self._wait_stream_process(process)
            time.sleep(0.1)

            if process.returncode == 0:
                self._send_final_result(1, "Command completed")
            else:
                self._send_final_result(0, f'Command exited with code {process.returncode}')
        except CommandCancelledError:
            self._send_final_result(0, 'Command cancelled')
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            self._send_final_result(0, 'Command timed out and was terminated')
        except Exception as e:
            self._send_final_result(0, f'Failed to execute command: {e}')

    @desc('Execute Python code and collect output', group='execution')
    @cancel_policy('cooperative')
    def pyexec(self, code, kwargs=None):
        """
        一次性返回版本。
        """
        try:
            return self._execute_python_collect(
                code,
                kwargs=kwargs,
                mode=get_python_execution_mode(),
                default_mode='inproc',
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            return 0, 'Command timed out'
        except Exception as e:
            return 0, f'Failed to execute code: {e}'

    @desc('Execute Python code with streaming output', group='execution', output='stream')
    @cancel_policy('cooperative')
    def pyexec_stream(self, code, kwargs=None):
        """
        流式返回版本。
        """
        try:
            return self._execute_python_stream(
                code,
                kwargs=kwargs,
                mode=get_python_execution_mode(),
                default_mode='inproc',
            )
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            return 0, 'Command timed out'
        except Exception as e:
            return 0, f'Failed to execute code: {e}'