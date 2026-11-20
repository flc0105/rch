from client.runtime.execution.runtime import ExecutionRuntime
from typing import Any, Callable

from client.commands.acmd.runner import ArgumentCommandRunner
from client.commands.runtime.catalog import CommandCatalog
from client.runtime.command_variable_resolver import CommandVariableResolver
from client.runtime.execution.request import ExecutionRequest
from client.commands.shell.runner import ShellCommandRunner


class CommandExecutor:
    """
    命令执行器。

    当前职责收口为：
    - 使用 CommandCatalog 获取平台命令对象 / acmd registry
    - 将 Command / ACMD 绑定到共享 ExecutionRuntime
    """

    def __init__(self, socket, execution=None, variable_resolver=None):
        self.socket = socket
        self.catalog = CommandCatalog(socket)
        self.execution = execution or ExecutionRuntime(socket)
        self.context_store = self.execution.context_store
        self.command_variable_resolver = variable_resolver or CommandVariableResolver(socket)
        self.shell_command_runner = ShellCommandRunner(self)
        self.argument_command_runner = ArgumentCommandRunner(self)

    def get_commands(self):
        """
        获取当前平台对应的命令实例（懒加载）
        """
        commands = self.catalog.get_commands()
        if hasattr(commands, 'set_command_runtime'):
            commands.set_command_runtime(self)
        return commands

    def get_command_manifest_payload(self):
        return self.catalog.get_command_manifest_payload()

    def get_command_variable_manifest(self):
        """
        获取普通 command 支持的 Client 动态变量清单。
        """
        return self.command_variable_resolver.get_manifest_payload()

    def complete_command_completion(self, payload: dict):
        from client.commands.runtime.completion import ClientCommandCompletionService
        commands = self.get_commands()
        service = getattr(self, '_completion_service', None)
        if service is None:
            service = ClientCommandCompletionService(commands)
            self._completion_service = service
        return service.complete(payload)

    def get_argument_command_registry(self):
        """
        获取当前平台对应的 acmd 注册表（懒加载）
        """
        return self.catalog.get_argument_command_registry()

    def _extract_timeout(self, options=None):
        return self.context_store.extract_timeout(options)

    def _build_request(self, command_id, options=None, payload_options=None) -> ExecutionRequest:
        timeout = self._extract_timeout(payload_options)
        if timeout is None:
            timeout = self._extract_timeout(options)
        return ExecutionRequest(command_id=command_id, timeout=timeout)

    def _bind_execution(self, commands, request: ExecutionRequest):
        """
        绑定命令实例与当前执行上下文。
        """
        execution_context = self.context_store.get_or_create(
            request.command_id,
            timeout=request.timeout,
        )
        if hasattr(commands, 'bind_execution'):
            commands.bind_execution(request.command_id, execution_context)
        else:
            commands.command_id = request.command_id
        return commands

    def _prepare_commands(self, request: ExecutionRequest):
        """
        获取命令实例并绑定当前 command_id
        """
        commands = self.get_commands()
        return self._bind_execution(commands, request)

    def _execute_with_cleanup(self, command_id, invoke: Callable[[], Any]):
        return self.execution.execute(command_id, invoke)

    def execute_bound_request(self, request: ExecutionRequest, invoke: Callable[[Any], Any]):
        def _runner():
            commands = self._prepare_commands(request)
            # Common entry checkpoint for command / acmd.
            commands._checkpoint()
            return invoke(commands)
        return self._execute_with_cleanup(request.command_id, _runner)

    def execute_command(self, command_id, command, options=None):
        """
        执行命令
        :param command_id: 命令id，用于返回结果时指定对应的命令id
        :param command: 命令字符串
        :param options: 执行选项（如 timeout）
        :return: 执行结果元组（状态和消息）
        """
        request = self._build_request(command_id, options=options)
        return self.shell_command_runner.execute(request, command)

    def execute_argument_command(self, command_id, payload: dict, options=None):
        """
        执行 acmd 结构化实验命令
        :param command_id: 命令id
        :param payload: 结构化命令负载
        :param options: 执行选项（如 timeout）
        :return: 执行结果元组（状态和消息）
        """
        request = self._build_request(command_id, options=options, payload_options=payload)
        return self.argument_command_runner.execute(request, payload)

    def sdk_command_names(self):
        """List exports without constructing or binding a platform command instance."""
        command_class = self.catalog._load_platform_command_class()
        from client.commands.shell.decorators import supports_shell_platform
        platform = self.catalog._get_platform_name()
        return sorted(name for name in dir(command_class)
                      if not name.startswith('_')
                      and hasattr(getattr(command_class, name, None), 'help')
                      and supports_shell_platform(getattr(command_class, name), platform))

    def resolve_sdk_command(self, scope, name):
        """SDK-only bridge; execute a real exported command within the current context."""
        commands = self.get_commands()
        commands.bind_execution(scope.command_id, scope.execution_context)
        return self.shell_command_runner._resolve_builtin_command(commands, name)
