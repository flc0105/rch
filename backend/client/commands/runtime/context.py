"""Client command execution context, shared by ordinary module-level handlers."""

from client.runtime.execution.scope import ExecutionScope


class ClientCommandContext(ExecutionScope):
    """Reusable runtime services and the currently bound execution; no commands live here."""

    def __init__(self, socket, platform):
        self.socket = socket
        self.command_platform = platform
        self.command_id = None
        self.execution_context = None
        self._command_runtime = None

    def bind_execution(self, command_id, execution_context=None):
        self.command_id = command_id
        self.execution_context = execution_context

    def set_command_runtime(self, runtime):
        self._command_runtime = runtime
