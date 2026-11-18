"""Shared Python execution for Shell pyexec and Script runs.

This service owns strategy selection and SDK context injection.  The strategies
continue to own cancellation/streaming behavior; result protocols stay at the
Shell and Script command boundaries.
"""

from client.config import runtime_config
from client.runtime.execution.python_execution.factory import build_python_execution_strategy


class PythonExecutionService:
    """One Python execution entry shared by Shell and Script callers."""

    def __init__(self, owner):
        self.owner = owner
        self._strategies = {}

    def execute(self, code, kwargs=None, *, mode='', default_mode='inproc',
                timeout=None, script_name=None, stream=False):
        key = (mode or '', default_mode or '')
        strategy = self._strategies.get(key)
        if strategy is None:
            strategy = build_python_execution_strategy(
                self.owner, mode=mode, default_mode=default_mode,
            )
            self._strategies[key] = strategy

        # Preserve the existing __context__ contract for both Script and pyexec.
        socket = getattr(self.owner, 'socket', None)
        command_id = getattr(self.owner, 'command_id', None)
        context = {
            'client_id': getattr(socket, 'client_id', '') or '',
            'command_id': command_id if command_id is not None else '',
        }
        try:
            from client.runtime.client_util import get_system_paths
            from core.device.local_identity import get_local_identity
            identity = get_local_identity()
            context.update({
                'hostname': identity.hostname,
                'machine_id': identity.machine_id,
                'platform': identity.os_alias,
                'os_alias': identity.os_alias,
                'os_type': identity.os_type,
                'os_ver': identity.os_version,
                'arch': identity.arch,
                'system_paths': get_system_paths(),
            })
        except Exception:
            pass
        if script_name:
            context['script_name'] = str(script_name).strip()
        context['client_session_token'] = str(
            getattr(socket, 'client_session_token', '') or ''
        )
        params = dict(kwargs or {})
        params['__context__'] = context
        run = strategy.execute_stream if stream else strategy.execute_collect
        effective_timeout = runtime_config.COMMAND_DEFAULT_STREAM_TIMEOUT if timeout is None else timeout
        return run(code, kwargs=params, timeout=effective_timeout)
