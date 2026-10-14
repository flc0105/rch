import contextlib
import io
import traceback

from client.commands.runtime.context import CommandCancelledError, CommandTimeoutError
from client.runtime.sdk.context import build_script_sdk_globals, use_script_sdk_context
from client.commands.strategies.python_execution.base import PythonExecutionStrategy


USER_FACING_SCRIPT_ERRORS = {
    'KeychainError',
    'ScriptSdkArtifactError',
    'ScriptSdkScriptsError',
    'ScriptSdkCommandError',
    'ScriptSdkExternalToolError',
    'ScriptSdkWorkspaceError',
    'ClientApiError',
    'ScriptSdkInteractionError',
}


def _is_user_facing_script_error(exc: Exception) -> bool:
    module_name = str(exc.__class__.__module__ or '')
    if exc.__class__.__name__ not in USER_FACING_SCRIPT_ERRORS:
        return False
    return module_name.startswith(('client.runtime', 'client.http'))


def _format_user_facing_script_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return f"\n[ERROR] Script execution failed:\n{exc.__class__.__name__}: {message}\n"


class InProcessPythonExecutionStrategy(PythonExecutionStrategy):
    MODE_NAME = 'inproc'

    def is_cancel_supported(self) -> bool:
        return False

    def _build_exec_globals(self, kwargs=None):
        if kwargs is None:
            kwargs = {}

        # exec_globals = {}
        exec_globals = {'__name__': '__main__'} # 支持if __name__ == '__main__'
        exec_globals.update(kwargs)  # 用户传入的参数

        # 注入 Script SDK：artifact / command / keychains / 已导出的 client 命令快捷函数。
        exec_globals.update(build_script_sdk_globals(self.owner, kwargs))

        # 同时注入 kwargs 本身，方便脚本使用
        exec_globals['kwargs'] = kwargs
        return exec_globals

    def execute_collect(self, code, kwargs=None, timeout=None):
        self.configure_context()

        output = io.StringIO()
        try:
            exec_globals = self._build_exec_globals(kwargs)
            with use_script_sdk_context(self.owner, kwargs):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    exec(code, exec_globals)
            return 1, output.getvalue()
        except Exception as exc:
            if _is_user_facing_script_error(exc):
                output.write(_format_user_facing_script_error(exc))
            else:
                error_msg = traceback.format_exc()
                output.write(f"\n[ERROR] Script execution failed:\n{error_msg}")
            return 0, output.getvalue()

    def execute_stream(self, code, kwargs=None, timeout=None):
        """
        执行 Python 代码并生成输出流
        """
        self.configure_context()

        if kwargs is None:
            kwargs = {}

        try:
            import sys

            # 创建自定义的 StringIO 来捕获输出
            class StreamGenerator:
                def __init__(self, owner):
                    self.owner = owner
                    self.buffer = ''

                def write(self, text):
                    if text:
                        self.buffer += text
                        lines = self.buffer.split('\n')
                        self.buffer = lines[-1]
                        for line in lines[:-1]:
                            if line:
                                self.owner._send_interim_result(1, line, 0)

                def flush(self):
                    if self.buffer:
                        self.owner._send_interim_result(1, self.buffer, 0)
                        self.buffer = ''

            # 保存原始 stdout/stderr
            old_stdout = sys.stdout
            old_stderr = sys.stderr

            # 创建捕获器
            generator = StreamGenerator(self.owner)

            sys.stdout = generator
            sys.stderr = generator

            try:
                exec_globals = self._build_exec_globals(kwargs)
                with use_script_sdk_context(self.owner, kwargs):
                    exec(code, exec_globals)
                generator.flush()
            except Exception as e:
                if _is_user_facing_script_error(e):
                    message = _format_user_facing_script_error(e).strip()
                else:
                    message = f'Error: {e}'
                self.owner._send_interim_result(0, message, 0)
                return 0, f'Execution failed: {e}'
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

            self.owner._send_final_result(1, "Code execution completed")

        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out'
        except Exception as e:
            return 0, f'Failed to execute code: {e}'





