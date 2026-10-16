import base64
import pickle
import subprocess
import sys
import time

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError
from client.commands.strategies.python_execution.base import PythonExecutionStrategy


class SubprocessPipePythonExecutionStrategy(PythonExecutionStrategy):
    MODE_NAME = 'subprocess_pipe'

    def is_cancel_supported(self) -> bool:
        return True

    def _serialize_kwargs(self, kwargs) -> str:
        if kwargs is None:
            kwargs = {}
        payload = pickle.dumps(kwargs)
        return base64.b64encode(payload).decode('ascii')

    def _build_bootstrap_script(self, code, kwargs=None) -> str:
        """
        这里保留 bootstrap 概念，但不落地临时文件。
        它只负责把用户代码和 kwargs 包成一段完整的 Python 文本，
        然后直接通过 stdin 管道喂给子进程。
        """
        from types import SimpleNamespace
        from client.commands.runtime.command_variable_resolver import CommandVariableResolver

        payload = dict(kwargs or {})
        script_context = dict(payload.get('__context__') or {})
        resolver = CommandVariableResolver(SimpleNamespace(client_id=script_context.get('client_id', '')))
        # 子进程的 argv / PID 与 Client 不同，先保存 Client 本体的取值。
        script_context['__rch_variables__'] = {
            name: resolver.resolve('${rch:' + name + '}', command_id=script_context.get('command_id'))
            for name in ('exec_path', 'launch_command', 'runtime', 'pid', 'client_id', 'command_id')
        }
        payload['__context__'] = script_context
        kwargs_payload = self._serialize_kwargs(payload)

        return f"""import base64
import pickle
import traceback

from client.runtime.sdk.context import build_script_sdk_globals, use_script_sdk_context

USER_CODE = {code!r}
KWARGS_PAYLOAD = {kwargs_payload!r}

try:
    kwargs = pickle.loads(base64.b64decode(KWARGS_PAYLOAD.encode('ascii')))
except Exception:
    kwargs = {{}}

exec_globals = {{'__name__': '__main__'}}
exec_globals.update(kwargs)
exec_globals.update(build_script_sdk_globals(None, kwargs))
exec_globals['kwargs'] = kwargs

try:
    with use_script_sdk_context(None, kwargs):
        exec(compile(USER_CODE, '<remote_pyexec>', 'exec'), exec_globals)
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    raise
"""

    def _start_python_process(self):
        process = subprocess.Popen(
            [sys.executable, '-u', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            **self.owner._build_process_creation_kwargs()
        )
        self.owner._register_cancel_handler(lambda: self.owner._terminate_process(process))
        return process

    def execute_collect(self, code, kwargs=None, timeout=None):
        self.configure_context()

        process = None
        try:
            process = self._start_python_process()
            bootstrap_code = self._build_bootstrap_script(code, kwargs=kwargs)

            stdout, stderr = process.communicate(
                input=bootstrap_code,
                timeout=self.owner._resolve_timeout(timeout),
            )
            # A process cancel handler may terminate the child while communicate()
            # is blocked. Distinguish confirmed cancellation from an ordinary exit.
            self.owner._checkpoint(fallback_timeout=timeout)

            if process.returncode == 0:
                return 1, stdout or ''
            return 0, (stdout or '') + (stderr or '')
        except CommandCancelledError:
            if process is not None:
                self.owner._terminate_process(process)
            raise
        except CommandTimeoutError:
            if process is not None:
                self.owner._terminate_process(process)
            raise
        except subprocess.TimeoutExpired:
            if process is not None:
                self.owner._terminate_process(process)
            raise
        except Exception:
            if process is not None:
                self.owner._terminate_process(process)
            raise

    def execute_stream(self, code, kwargs=None, timeout=None):
        """
        在子进程中执行 Python 代码，实时流式输出，支持强制取消
        """
        self.configure_context()

        process = None
        try:
            process = self._start_python_process()
            bootstrap_code = self._build_bootstrap_script(code, kwargs=kwargs)
            process.stdin.write(bootstrap_code)
            process.stdin.close()

            def read_stream(stream, is_stderr=False):
                for line in iter(stream.readline, ''):
                    self.owner._checkpoint(fallback_timeout=timeout)
                    if line:
                        status = 0 if is_stderr else 1
                        self.owner._send_interim_result(status, line.rstrip('\n'), 0)

            import threading
            stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, False))
            stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, True))
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            while True:
                self.owner._checkpoint(fallback_timeout=timeout)
                if process.poll() is not None:
                    break
                time.sleep(0.1)

            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

            if process.returncode == 0:
                self.owner._send_final_result(1, "Code execution completed")
            else:
                self.owner._send_final_result(0, f"Process exited with code {process.returncode}")

        except CommandCancelledError:
            if process and process.poll() is None:
                self.owner._terminate_process(process)
            self.owner._send_final_result(0, 'Command cancelled')
        except (CommandTimeoutError, subprocess.TimeoutExpired):
            if process and process.poll() is None:
                self.owner._terminate_process(process)
            self.owner._send_final_result(0, 'Command timed out')
        except Exception as e:
            if process and process.poll() is None:
                self.owner._terminate_process(process)
            self.owner._send_final_result(0, f'Failed to execute code: {e}')





