import inspect
from typing import Any, Callable

from client.commands.arguments.errors import ArgumentCommandValidationError
from client.commands.arguments.help_builder import ArgumentCommandHelpBuilder
from client.commands.arguments.validator import ArgumentCommandValidator


class ArgumentCommandRegistry:
    """
    acmd 实验命令注册表。

    职责：
    - 扫描命令对象上的实验命令处理器
    - 管理 handler + spec
    - 统一 help / 参数校验 / 执行分发
    - 输出 acmd 自动补全候选
    """

    HELP_OPTION_NAME = 'help'
    HELP_COMMAND_NAME = 'help'

    def __init__(self, commands):
        self.commands = commands
        self.help_builder = ArgumentCommandHelpBuilder()
        self.validator = ArgumentCommandValidator()
        self._entries = self._collect_entries()

    def _collect_entries(self) -> dict:
        """
        扫描并收集所有已注册的实验命令处理器
        """
        entries = {}

        for _, method in inspect.getmembers(
            self.commands,
            lambda x: inspect.ismethod(x) or inspect.isfunction(x)
        ):
            command_name = getattr(method, 'argument_command_name', '')
            if not command_name:
                continue

            spec = getattr(method, 'argument_command_spec', None)
            entries[command_name] = {
                'handler': method,
                'spec': spec,
            }

        return entries

    def has_command(self, name: str) -> bool:
        """
        判断是否存在指定实验命令
        """
        return name in self._entries

    def list_command_entries(self) -> list[dict]:
        """
        返回所有已注册 acmd 命令及其简短帮助信息
        """
        result = []

        for command_name, entry in self._entries.items():
            spec = entry.get('spec')
            description = ''

            if spec is not None:
                description = (spec.description or '').strip()

            result.append({
                'name': command_name,
                'description': description or 'No description',
            })

        result.sort(key=lambda item: item['name'])
        return result

    def get_manifest_payload(self) -> list[dict]:
        """Describe registered ACMD handlers and their completion templates."""
        from client.commands.runtime.manifest_metadata import command_metadata

        payload = [{
            'name': 'acmd help',
            'help': 'List all registered structured commands',
            'group': 'acmd',
            'suggest': True,
            **command_metadata(None, kind='acmd'),
        }]
        for item in self.list_command_entries():
            command_name = item['name'].strip()
            if not command_name:
                continue
            handler = self._entries[command_name]['handler']
            metadata = command_metadata(handler, kind='acmd')
            payload.append({
                'name': f'acmd {command_name}',
                'help': item['description'],
                'group': 'acmd',
                'suggest': True,
                **metadata,
            })
        return payload

    def execute(self, payload: dict):
        """
        执行实验命令
        payload 结构：
        {
            'name': 'msgbox',
            'args': {'title': 'aaa', 'text': 'bbb'},
            'raw': 'acmd msgbox --title aaa --text bbb'
        }
        """
        if not isinstance(payload, dict):
            return 0, 'Invalid acmd payload'

        command_name = (payload.get('name') or '').strip()
        raw_args = payload.get('args') or {}

        if not command_name:
            return 0, 'Missing acmd command name'

        if not isinstance(raw_args, dict):
            return 0, 'Invalid acmd args payload'

        if command_name == self.HELP_COMMAND_NAME:
            return self._execute_help_command(raw_args)

        entry = self._entries.get(command_name)
        if entry is None:
            return 0, f'acmd command not supported on this platform: {command_name}'

        handler = entry.get('handler')
        spec = entry.get('spec')

        try:
            if spec is not None:
                raw_args_for_help = self.validator.normalize_arg_keys(spec, raw_args)
                normalized_help_flag = self._normalize_help_flag(
                    raw_args_for_help.get(self.HELP_OPTION_NAME, False)
                )
                if normalized_help_flag:
                    return 1, self.help_builder.build(spec)

                normalized_args = self.validator.normalize(spec, raw_args)
            else:
                normalized_args = raw_args

            return self._invoke_handler(handler, normalized_args, payload)
        except ArgumentCommandValidationError as e:
            return 0, str(e)
        except Exception as e:
            return 0, f'acmd execution failed: {e}'

    def _execute_help_command(self, raw_args: dict) -> tuple[int, str]:
        """
        执行 acmd help
        支持：
        - acmd help
        - acmd help <command>
        """
        positional_args = raw_args.get('_args') or []
        if not isinstance(positional_args, list):
            return 0, 'Invalid acmd help args'

        if not positional_args:
            return 1, self.help_builder.build_command_list(self.list_command_entries())

        target_command_name = str(positional_args[0] or '').strip()
        if not target_command_name:
            return 0, 'Usage: acmd help [command]'

        entry = self._entries.get(target_command_name)
        if entry is None:
            return 0, f'acmd command not found: {target_command_name}'

        spec = entry.get('spec')
        if spec is None:
            return 0, f'acmd help is not available for: {target_command_name}'

        return 1, self.help_builder.build(spec)

    def _normalize_help_flag(self, value: Any) -> bool:
        if value is True:
            return True

        if isinstance(value, str):
            text = value.strip().lower()
            if text in ('1', 'true', 'yes', 'on'):
                return True
            if text in ('0', 'false', 'no', 'off', ''):
                return False

        return False

    def _invoke_handler(self, handler: Callable, args_dict: dict, payload: dict):
        parameters_count = len(inspect.signature(handler).parameters)

        if parameters_count >= 2:
            return handler(args_dict, payload)

        return handler(args_dict)
