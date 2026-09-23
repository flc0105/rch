import os
import shlex
import subprocess
import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError
from client.external_tools.common import ExternalToolCommon
from client.external_tools.launcher import apply_external_tool_launcher


class ExternalToolCliExec(ExternalToolCommon):
    """CLI-facing external tool executable operations."""

    def which_payload(self, payload: dict) -> str:
        status = self.install_status_payload(payload)
        executable_path = status.get('executable_path') or ''

        if not status.get('installed'):
            raise FileNotFoundError(status.get('message') or 'External tool is not installed')

        if not executable_path or not os.path.exists(executable_path):
            raise FileNotFoundError(f'External tool executable not found: {executable_path}')

        return executable_path

    def execute_cli_payload(self, payload: dict):
        try:
            status = self.install_status_payload(payload)
            executable_path = status.get('executable_path') or ''

            if not status.get('installed'):
                self.command_host._send_final_result(0, status.get('message') or 'External tool is not installed')
                return

            if not executable_path or not os.path.exists(executable_path):
                self.command_host._send_final_result(0, f'External tool executable not found: {executable_path}')
                return

            self.chmod(executable_path)

            raw_args = str(payload.get('raw_args') or '').strip()
            argv_extra = payload.get('argv_extra')
            if not isinstance(argv_extra, list):
                argv_extra = shlex.split(raw_args) if raw_args else []

            argv = [executable_path] + [str(item) for item in argv_extra]

            exec_options = payload.get('exec_options') if isinstance(payload.get('exec_options'), dict) else {}
            argv = apply_external_tool_launcher(argv, exec_options.get('launcher'))
            cwd = self.expand_path(exec_options.get('cwd') or os.getcwd())
            if not os.path.isdir(cwd):
                raise FileNotFoundError(f'external tool cli cwd does not exist: {cwd}')

            timeout_sec = exec_options.get('timeout_sec')
            try:
                timeout_sec = float(timeout_sec)
            except Exception:
                timeout_sec = None
            if timeout_sec is not None and timeout_sec <= 0:
                timeout_sec = None

            process = subprocess.Popen(
                argv,
                shell=False,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **self.command_host._build_process_creation_kwargs()
            )
            self.command_host._register_cancel_handler(lambda: self.command_host._terminate_process(process))

            # _start_output_threads 当前签名是 _start_output_threads(process)，超时只交给 wait 层。
            self.command_host._start_output_threads(process)
            self.command_host._wait_process_with_cancel_support(process, timeout=timeout_sec)
            time.sleep(0.1)

            if process.returncode == 0:
                self.command_host._send_final_result(1, 'Command completed')
            else:
                self.command_host._send_final_result(0, f'Command exited with code {process.returncode}')

        except CommandCancelledError:
            self.command_host._send_final_result(0, 'Command cancelled')
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            self.command_host._send_final_result(0, 'Command timed out and was terminated')
        except Exception as e:
            self.command_host._send_final_result(0, f'Failed to execute external tool: {e}')
