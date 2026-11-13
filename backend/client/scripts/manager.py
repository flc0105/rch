import subprocess
from core.protocol.control import ScriptAction

from client.config import runtime_config
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from core.protocol.script_execution import validate_payload_modes, ExecutionMode, OutputMode
from core.utils.script_metadata import read_script_metadata_from_source
from client.runtime.execution.python_process import PythonProcessExecutionMixin
from client.runtime.execution.scope import ExecutionScope
from client.runtime.sdk.command import ScriptCommandAccess


class ScriptManager:
    """Own foreground Script execution and its per-run SDK context."""

    def __init__(self, command_access: ScriptCommandAccess | None = None):
        self.command_access = command_access

    @staticmethod
    def cancel_policy(action, payload):
        if action != ScriptAction.RUN or not isinstance(payload, dict):
            return None
        try:
            return ExecutionMode(payload.get('execution_mode')).cancel_policy
        except ValueError:
            return None

    def execute(self, scope, action, payload):
        if action != ScriptAction.RUN:
            return 0, f'Unsupported script Control action: {action}'
        source, params, name = (payload.get(key) for key in ('source', 'params', 'script_name'))
        if not isinstance(source, str) or not source.strip() or not isinstance(params, dict) or not isinstance(name, str) or not name.strip():
            return 0, 'Invalid script Control payload'
        try:
            modes = validate_payload_modes(read_script_metadata_from_source(source, name),
                                           payload.get('execution_mode'), payload.get('output_mode'))
        except ValueError as exc:
            return 0, str(exc)
        execution = ScriptExecution(scope.socket, scope.execution_context, self.command_access)
        return execution.run_script(source, params, name, modes=modes)


class ScriptExecution(PythonProcessExecutionMixin, ExecutionScope):
    def __init__(self, socket, context, command_access=None):
        super().__init__(socket, context)
        self.command_access = command_access

    def sdk_command_names(self):
        return self.command_access.names() if self.command_access else []

    def resolve_sdk_command(self, name):
        return self.command_access.resolve(self, name) if self.command_access else None

    def run_script(self, code, kwargs=None, script_name=None, *, modes):
        """
        Script 使用 Server 已解析且 Client 已校验的本次执行模式。
        """
        script_timeout = runtime_config.SCRIPT_DEFAULT_TIMEOUT
        self._set_timeout(script_timeout)
        self._set_cancel_policy(modes.execution_mode.cancel_policy, 'Current Python execution mode does not support cancellation')
        try:
            execute = self._execute_python_stream if modes.output_mode is OutputMode.STREAM else self._execute_python_collect
            result = execute(
                code,
                kwargs=kwargs,
                script_name=script_name,
                mode=modes.execution_mode.value,
                default_mode='inproc',
                timeout=script_timeout,
            )
        except (subprocess.TimeoutExpired, CommandTimeoutError) as exc:
            return self._interrupted('timed_out', getattr(exc, 'output', ''), f'Script timed out after {script_timeout} seconds')
        except CommandCancelledError as exc:
            return self._interrupted('cancelled', getattr(exc, 'output', ''), 'Script cancelled')
        # In-process execution returns control only after user Python finishes.
        context = self._get_execution_context()
        if context and context.is_timeout_expired(fallback_timeout=script_timeout):
            return self._interrupted('timed_out', result[1], f'Script exceeded timeout of {script_timeout} seconds')
        return result

    @staticmethod
    def _interrupted(reason, output, message):
        text = (str(output) + ('\n' if not str(output).endswith('\n') else '') if output else '') + message
        return 0, {'event_type': 'cancelled' if reason == 'cancelled' else 'error',
                   'failure_reason': reason, 'text': text}


