import inspect
from types import MethodType
from typing import Any, Callable

from core.commands.argument_errors import ArgumentCommandValidationError
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.commands.acmd.help import ArgumentCommandHelpBuilder
from core.commands.argument_validator import ArgumentCommandValidator
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.platform.normalization import normalize_platform_alias
from core.utils.command_output import StructuredCommandResult, PRESENTATION_FORMATS


_DISPLAY_SPEC = ArgumentCommandSpec(
    name='acmd_display', options=[
        ArgumentOptionSpec('format', 'str', default='', allow_empty=False, alias='f',
                           choices=tuple(sorted(PRESENTATION_FORMATS))),
        ArgumentOptionSpec('json', 'flag', default=False),
    ],
)
_DISPLAY_KEYS = frozenset(('format', 'f', 'json'))


class ArgumentCommandRegistry:
    """
    ACMD 显式命令注册表。

    职责：
    - 由 Common / Platform 模块显式注册处理器
    - 管理 handler + spec
    - 统一 help / 参数校验 / 执行分发
    - 输出 acmd 自动补全候选
    """

    HELP_OPTION_NAME = 'help'
    HELP_COMMAND_NAME = 'help'

    def __init__(self, commands):
        self.context = commands
        self.help_builder = ArgumentCommandHelpBuilder()
        self.validator = ArgumentCommandValidator()
        self._entries = {}

    def register(self, handler):
        """Register exactly one decorated command from its owner module."""
        name = getattr(handler, 'argument_command_name', None)
        spec = getattr(handler, 'argument_command_spec', None)
        if not name or spec is None or spec.name != name:
            raise ValueError('ACMD requires matching command name and ArgumentCommandSpec')
        supported = getattr(handler, 'argument_command_platforms', None)
        platform = normalize_platform_alias(self.context.command_platform)
        if supported is not None and platform not in supported:
            return
        if name in self._entries:
            raise ValueError(f'Duplicate ACMD registration: {name}')
        self._entries[name] = {'handler': MethodType(handler, self.context), 'spec': spec}

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
            completion_specs = []
            seen_completion_specs = set()
            argument_spec = self._entries[command_name].get('spec')
            if argument_spec is not None:
                for option in argument_spec.options:
                    completion = getattr(option, 'completion', None)
                    if completion is None:
                        continue
                    key = (completion.provider, completion.kinds)
                    if key in seen_completion_specs:
                        continue
                    seen_completion_specs.add(key)
                    completion_specs.append(completion.to_dict())
            payload.append({
                'name': f'acmd {command_name}',
                'help': item['description'],
                'group': 'acmd',
                'suggest': True,
                **metadata,
                **({'completion': completion_specs} if completion_specs else {}),
            })
        return payload

    def execute(self, payload: dict):
        """
        执行实验命令
        payload 结构：
        {
            'name': 'msgbox',
            'args': {'title': 'aaa', 'text': 'bbb'},
            'raw': 'acmd msgbox --title aaa --message bbb'
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
                business_args = {key: value for key, value in raw_args.items() if key not in _DISPLAY_KEYS}
                raw_args_for_help = self.validator.normalize_arg_keys(spec, business_args)
                normalized_help_flag = self._normalize_help_flag(
                    raw_args_for_help.get(self.HELP_OPTION_NAME, False)
                )
                if normalized_help_flag:
                    return 1, self.help_builder.build(spec)

                display_args = {key: value for key, value in raw_args.items() if key in _DISPLAY_KEYS}
                display = self.validator.normalize(_DISPLAY_SPEC, display_args)
                requested = 'json' if display['json'] else (display['format'] or None)
                normalized_args = self.validator.normalize(spec, business_args)
            else:
                normalized_args = raw_args
                requested = None

            result = self._invoke_handler(handler, normalized_args, payload)
            if isinstance(result, StructuredCommandResult):
                # Display compatibility is scoped to the actual successful result.
                # Message-only outcomes keep their ordinary feedback.
                if requested and result.status == 1 and requested not in result.formats:
                    if result.source == 'message':
                        requested = None
                    else:
                        # The handler has already produced data. Retain it in the
                        # Result event for History, but report the display error.
                        event = result.as_event(requested=requested)
                        event['status'] = 'error'
                        event['message'] = (f'Unsupported format for this result: {requested}. '
                                            f'Available: {", ".join(result.formats)}.')
                        return 0, event
                return result.status, result.as_event(requested=requested)
            return result
        except ArgumentCommandValidationError as e:
            return 0, str(e)
        except (CommandCancelledError, CommandTimeoutError):
            raise
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
