import io
import traceback

from client.runtime.execution.python_execution.output import capture_output, StreamOutput
from client.runtime.sdk.context import build_script_sdk_globals, use_script_sdk_context
from client.runtime.execution.python_execution.base import PythonExecutionStrategy


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


def _is_user_facing_script_error(exc: BaseException) -> bool:
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

    def _execute(self, code, kwargs, output):
        self.configure_context()
        try:
            exec_globals = self._build_exec_globals(kwargs)
            with use_script_sdk_context(self.owner, kwargs):
                with capture_output(output, output):
                    exec(code, exec_globals)
            return 1, ''
        # User scripts must not propagate interpreter-exit exceptions into Client.wait().
        except BaseException as exc:
            message = (_format_user_facing_script_error(exc) if _is_user_facing_script_error(exc)
                       else f"\n[ERROR] Script execution failed:\n{traceback.format_exc()}")
            return 0, message
        finally:
            output.flush()

    def execute_collect(self, code, kwargs=None, timeout=None):
        output = io.StringIO()
        status, message = self._execute(code, kwargs, output)
        return status, output.getvalue() + message

    def execute_stream(self, code, kwargs=None, timeout=None):
        output = StreamOutput(lambda text: self.owner._send_interim_result(1, text, 0))
        status, message = self._execute(code, kwargs, output)
        return status, message or 'Code execution completed'
