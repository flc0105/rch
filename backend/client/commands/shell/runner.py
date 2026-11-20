import inspect
from typing import Any

from client.runtime.command_variable_resolver import CommandVariableResolutionError
from client.commands.runtime.interrupts import get_command_timeout
from client.commands.shell.decorators import supports_shell_platform
from core.device.local_identity import get_local_identity
from client.runtime.execution.request import ExecutionRequest
from core.utils.command_output import render_structured_result
from core.utils.parsing import parse


class ShellCommandRunner:
    """
    shell-like 命令执行链。

    只处理普通 command 字符串：
    - 先尝试平台内置命令
    - 未命中时回退到 shell 执行
    """

    def __init__(self, executor):
        self.executor = executor

    def _render_command_result(self, result, output_format='text'):
        return render_structured_result(result, output_format=output_format)

    def _resolve_builtin_output_format(self, arg: Any) -> str:
        return 'json' if '--json' in str(arg or '').split() or str(arg or '').strip().lower() == 'json' else 'text'

    def _resolve_builtin_command(self, commands, name):
        """
        解析平台内置命令函数；如果不存在或不是导出命令，则返回 None
        """
        func = self.executor.catalog.get_shell_command(name)
        if func is None:
            return None

        platform = getattr(commands, 'command_platform', None) or get_local_identity().os_alias
        if not supports_shell_platform(func, platform):
            # A known, unavailable builtin must not be forwarded to the OS shell.
            return lambda: (0, f'Command not supported on this platform: {name}')
        return func

    def _resolve_default_command(self, commands, raw_command):
        """Fallback to the OS shell only when its platform capability is enabled."""
        handler = self.executor.catalog.get_shell_command('shell')
        platform = getattr(commands, 'command_platform', None) or get_local_identity().os_alias
        if not supports_shell_platform(handler, platform):
            return lambda: (0, 'OS shell execution is unavailable on this platform')
        return lambda: handler(raw_command)

    def _apply_command_policy(self, commands, func):
        context = getattr(commands, 'execution_context', None)
        if context is None:
            return
        budget = get_command_timeout(func, getattr(commands, 'command_platform', None))
        if budget is not None:
            context.set_timeout(budget)
        mode = getattr(func, 'command_cancel_mode', 'none')
        context.set_cancel_policy(
            mode=mode,
            message=getattr(func, 'command_cancel_message', '') or
                    'Command does not support cancellation',
        )
        commands._checkpoint()

    def _invoke_command_method(self, func, arg):
        """
        调用命令函数
        """
        if len(inspect.signature(func).parameters):
            return func(arg)
        return func()

    def execute(self, request: ExecutionRequest, command):
        try:
            resolved_command = self.executor.command_variable_resolver.resolve(
                command,
                command_id=request.command_id,
            )
        except CommandVariableResolutionError as e:
            return 0, f'Failed to resolve command variable: {e}'

        def _invoke(commands):
            name, arg = parse(resolved_command)

            builtin_command = self._resolve_builtin_command(commands, name)
            if builtin_command:
                self._apply_command_policy(commands, builtin_command)
                result = self._invoke_command_method(builtin_command, arg)
                return self._render_command_result(
                    result,
                    output_format=self._resolve_builtin_output_format(arg),
                )

            # Shell fallback uses the same managed subprocess as the registered shell command.
            self._apply_command_policy(commands, self.executor.catalog.get_shell_command('shell'))
            default_command = self._resolve_default_command(commands, resolved_command)
            return default_command()

        return self.executor.execute_bound_request(request, _invoke)
