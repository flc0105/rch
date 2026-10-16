import inspect
from typing import Any

from client.commands.runtime.command_variable_resolver import CommandVariableResolutionError
from client.commands.runtime.request import CommandExecutionRequest
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
        return 'json' if str(arg or '').strip().lower() in ('json', '--json') else 'text'

    def _resolve_builtin_command(self, commands, name):
        """
        解析平台内置命令方法；如果不存在或不是导出命令，则返回 None
        """
        if not hasattr(commands, name):
            return None

        func = getattr(commands, name)
        if not hasattr(func, 'help'):
            return None

        return func

    def _resolve_default_command(self, commands, raw_command):
        """
        默认回退到 shell 执行
        """
        return lambda: commands.shell(raw_command)

    def _apply_command_policy(self, commands, func):
        context = getattr(commands, 'execution_context', None)
        if context is None:
            return
        budget = getattr(func, 'command_timeout', None)
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
        调用命令方法
        """
        if len(inspect.signature(func).parameters):
            return func(arg)
        return func()

    def execute(self, request: CommandExecutionRequest, command):
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
            self._apply_command_policy(commands, getattr(commands, 'shell'))
            default_command = self._resolve_default_command(commands, resolved_command)
            return default_command()

        return self.executor.execute_bound_request(request, _invoke)
