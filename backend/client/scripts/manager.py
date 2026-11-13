import subprocess

from client.config import runtime_config
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.runtime.execution.python_execution.factory import get_python_execution_mode
from client.runtime.execution.python_process import PythonProcessExecutionMixin
from client.runtime.execution.scope import ExecutionScope
from client.runtime.sdk.command import ScriptCommandAccess


class ScriptManager:
    """Own foreground Script execution and its per-run SDK context."""

    def __init__(self, command_access: ScriptCommandAccess | None = None):
        self.command_access = command_access

    def execute(self, scope, action, payload):
        if action != 'run':
            return 0, f'Unsupported script Control action: {action}'
        source, params, name = (payload.get(key) for key in ('source', 'params', 'script_name'))
        if not isinstance(source, str) or not source.strip() or not isinstance(params, dict) or not isinstance(name, str) or not name.strip():
            return 0, 'Invalid script Control payload'
        execution = ScriptExecution(scope.socket, scope.execution_context, self.command_access)
        return execution.run_script(source, params, name)


class ScriptExecution(PythonProcessExecutionMixin, ExecutionScope):
    def __init__(self, socket, context, command_access=None):
        super().__init__(socket, context)
        self.command_access = command_access

    def sdk_command_names(self):
        return self.command_access.names() if self.command_access else []

    def resolve_sdk_command(self, name):
        return self.command_access.resolve(self, name) if self.command_access else None

    def run_script(self, code, kwargs=None, script_name=None):
        """
        Script 使用当前 Client 配置选择 Python 执行策略，收集普通输出。
        """
        script_timeout = runtime_config.SCRIPT_DEFAULT_TIMEOUT
        self._set_timeout(script_timeout)
        try:
            result = self._execute_python_collect(
                code,
                kwargs=kwargs,
                script_name=script_name,
                mode=get_python_execution_mode(),
                default_mode='inproc',
                timeout=script_timeout,
            )
        except (subprocess.TimeoutExpired, CommandTimeoutError):
            return 0, f'Script timed out after {script_timeout} seconds'
        except CommandCancelledError:
            return 0, 'Script cancelled'
        # In-process execution returns control only after user Python finishes.
        context = self._get_execution_context()
        if context and context.is_timeout_expired(fallback_timeout=script_timeout):
            return 0, f'{result[1]}\nScript exceeded timeout of {script_timeout} seconds'
        return result


