from typing import Any, Callable

from client.commands.runtime.acmd_runner import ArgumentCommandRunner
from client.commands.runtime.catalog import CommandCatalog
from client.commands.runtime.command_variable_resolver import CommandVariableResolver
from client.commands.runtime.context_store import CommandExecutionContextStore
from client.commands.runtime.request import CommandExecutionRequest
from client.commands.runtime.script_runner import ScriptCommandRunner
from client.jobs.command_control import ClientJobControl
from client.commands.runtime.shell_command_runner import ShellCommandRunner


class CommandExecutor:
    """
    命令执行器。

    当前职责收口为：
    - 使用 CommandCatalog 获取平台命令对象 / acmd registry
    - 使用 CommandExecutionContextStore 管理单次命令生命周期
    - 只负责三类命令执行链的公共上下文绑定和清理
    """

    def __init__(self, socket):
        self.socket = socket
        self.catalog = CommandCatalog(socket)
        self.context_store = CommandExecutionContextStore()
        self.command_variable_resolver = CommandVariableResolver(socket)
        self.shell_command_runner = ShellCommandRunner(self)
        self.argument_command_runner = ArgumentCommandRunner(self)
        self.script_command_runner = ScriptCommandRunner(self)

    def get_commands(self):
        """
        获取当前平台对应的命令实例（懒加载）
        """
        commands = self.catalog.get_commands()
        if hasattr(commands, 'set_command_runtime'):
            commands.set_command_runtime(self)
        return commands

    def get_command_variable_manifest(self):
        """
        获取普通 command 支持的 Client 动态变量清单。
        """
        return self.command_variable_resolver.get_manifest_payload()

    def get_argument_command_registry(self):
        """
        获取当前平台对应的 acmd 注册表（懒加载）
        """
        return self.catalog.get_argument_command_registry()

    def _extract_timeout(self, options=None):
        return self.context_store.extract_timeout(options)

    def _build_request(self, command_id, options=None, payload_options=None) -> CommandExecutionRequest:
        timeout = self._extract_timeout(payload_options)
        if timeout is None:
            timeout = self._extract_timeout(options)
        grant = None
        if isinstance(options, dict) and isinstance(options.get('__script_grant__'), dict):
            grant = options['__script_grant__']
        return CommandExecutionRequest(command_id=command_id, timeout=timeout,
                                       interaction_grant=grant)

    def _get_or_create_execution_context(self, command_id, timeout=None):
        return self.context_store.get_or_create(command_id, timeout=timeout)

    def _clear_execution_context(self, command_id):
        self.context_store.clear(command_id)

    def cancel_command(self, command_id: int, on_completion=None) -> dict:
        """
        请求取消指定命令；若被接受，原子注册最终完成回调。
        """
        return self.context_store.cancel(command_id, on_completion=on_completion)

    def on_command_completion(self, command_id: int, callback):
        context = self.context_store.get_existing(command_id)
        if context is None:
            return False
        context.on_completion(callback)
        return True

    def _bind_execution(self, commands, request: CommandExecutionRequest):
        """
        绑定命令实例与当前执行上下文。
        """
        execution_context = self._get_or_create_execution_context(
            request.command_id,
            timeout=request.timeout,
        )
        if hasattr(commands, 'bind_execution'):
            commands.bind_execution(request.command_id, execution_context)
        else:
            commands.command_id = request.command_id
        commands._interaction_grant = request.interaction_grant
        return commands

    def _prepare_commands(self, request: CommandExecutionRequest):
        """
        获取命令实例并绑定当前 command_id
        """
        commands = self.get_commands()
        return self._bind_execution(commands, request)

    def _execute_with_cleanup(self, command_id, invoke: Callable[[], Any]):
        try:
            return invoke()
        finally:
            # A cancellation ACK is only a request; execution reaches a terminal
            # state once the command has actually returned or raised.
            context = self.context_store.get_existing(command_id)
            if context is not None:
                context.finish()
            self._clear_execution_context(command_id)

    def execute_bound_request(self, request: CommandExecutionRequest, invoke: Callable[[Any], Any]):
        def _runner():
            commands = self._prepare_commands(request)
            try:
                # Common entry checkpoint for command / acmd / script, previously duplicated
                # through the shared execution entry, never command-specific wrappers.
                commands._checkpoint()
                return invoke(commands)
            finally:
                commands._interaction_grant = None

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

    def execute_job_control_command(self, command_id, payload_text: str, options=None):
        """Handle internal Server-owned Job RPC; never expose a Client CLI job command."""
        request = self._build_request(command_id, options=options)
        return self.execute_bound_request(
            request, lambda commands: ClientJobControl.execute(commands, payload_text),
        )

    def execute_script_command(self, command_id, script_text: str, kwargs=None, options=None):
        """
        执行 script 消息
        统一通过 CommandExecutor 入口分发，避免绕过命令执行器
        """
        request = self._build_request(command_id, options=options, payload_options=kwargs)
        return self.script_command_runner.execute(request, script_text, kwargs=kwargs)
