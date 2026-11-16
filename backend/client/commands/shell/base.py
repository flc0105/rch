from abc import ABC

from client.runtime.execution.scope import ExecutionResources, ExecutionResultMixin, ExecutionRuntimeMixin

class CommandBindingMixin:
    """
    命令绑定能力：
    - 持有 socket
    - 持有当前 command_id
    - 持有当前 execution_context
    - 持有 CommandExecutor 注入的运行时对象
    """

    def __init__(self, socket):
        self.socket = socket
        self.command_id = None
        self.execution_context = None
        self._command_runtime = None

    def bind_execution(self, command_id, execution_context=None):
        """
        绑定当前命令执行上下文
        """
        self.command_id = command_id
        self.execution_context = execution_context

    def set_command_runtime(self, runtime):
        """
        注入命令运行时对象（当前由 CommandExecutor 提供）
        """
        self._command_runtime = runtime

    def get_argument_command_registry(self):
        """
        统一 acmd registry 归属，避免 introspection 每次自行 new 一份。
        """
        if self._command_runtime is not None:
            getter = getattr(self._command_runtime, 'get_argument_command_registry', None)
            if callable(getter):
                return getter()
        return None


class CommandBase(CommandBindingMixin, ExecutionResultMixin, ExecutionRuntimeMixin, ExecutionResources, ABC):
    """命令基类，定义公共接口。"""
