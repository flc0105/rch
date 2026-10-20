import shlex
from functools import partial
from server.application.command.command_types import (
    COMMAND_TYPE_ACMD,
    COMMAND_TYPE_COMMAND,
    COMMAND_TYPE_SCRIPT,
)

class CommandPlanner:
    """
    命令规划器。

    职责：
    - 解析 acmd
    - 构造 alias / default / script / acmd 的远程执行参数
    - 决定非 builtin 命令如何分流
    - 不负责具体执行，只负责把 plan 交给 plan_executor

    说明：
    - builtin 命令仍由 BuiltinCommandHandler 处理
    - 这里聚焦的是“远程计划型命令”的规划与路由决策
    """

    ACMD_PREFIX = 'acmd'

    def __init__(self, alias_manager, plan_executor, error_executor, conn=None, alias_resolved_callback=None):
        self.alias_manager = alias_manager
        self.plan_executor = plan_executor
        self.error_executor = error_executor
        self.conn = conn
        self.alias_resolved_callback = alias_resolved_callback

    def _wrap_error(self, error):
        return partial(self.error_executor, error)

    def is_argument_command(self, cmd: str) -> bool:
        parts = shlex.split(cmd or '')
        return bool(parts) and parts[0] == self.ACMD_PREFIX

    def parse_argument_command(self, cmd: str) -> dict:
        """
        解析 acmd 命令格式
        格式：
        acmd <command> [--arg1 value1] [--arg2 value2] [--flag] [--key=value]
        返回：
        {
            'name': 'msgbox',
            'args': {...},
            'raw': 'acmd ...'
        }
        """
        parts = shlex.split(cmd)

        if len(parts) < 2:
            raise ValueError('Usage: acmd <command> [--key value] [--flag]')

        if parts[0] != self.ACMD_PREFIX:
            raise ValueError('Invalid acmd format')

        command_name = (parts[1] or '').strip()
        if not command_name:
            raise ValueError('Missing acmd command name')

        args_dict = {}
        positional_args = []
        index = 2

        while index < len(parts):
            token = parts[index]

            if token == '--':
                positional_args.extend(parts[index + 1:])
                break

            if token.startswith('--'):
                option_text = token[2:]
                if not option_text:
                    raise ValueError('Empty option name is not allowed')

                if '=' in option_text:
                    key, value = option_text.split('=', 1)
                    key = key.strip()
                    if not key:
                        raise ValueError('Empty option name is not allowed')
                    args_dict[key] = value
                    index += 1
                    continue

                key = option_text.strip()
                if not key:
                    raise ValueError('Empty option name is not allowed')

                # Kill's explicit boolean switches must not consume a following
                # short flag (-f/-9) as their option value.
                if command_name == 'kill' and key in ('force', 'no-confirm'):
                    args_dict[key] = True
                    index += 1
                    continue

                if index + 1 < len(parts) and not parts[index + 1].startswith('--'):
                    args_dict[key] = parts[index + 1]
                    index += 2
                    continue

                args_dict[key] = True
                index += 1
                continue

            positional_args.append(token)
            index += 1

        if positional_args:
            args_dict['_args'] = positional_args

        return {
            'name': command_name,
            'args': args_dict,
            'raw': cmd,
        }

    def build_alias_plan(self, name: str, arg: str) -> dict | None:
        try:
            alias_payload = self.alias_manager.resolve_alias(name, arg, conn=self.conn)
        except KeyError:
            return None

        return {
            'kind': 'remote_command',
            'command': alias_payload['command'],
            'command_type': COMMAND_TYPE_COMMAND,
            'extra': None,
            'alias_name': alias_payload['alias'],
            'alias_platform': alias_payload['platform'],
        }

    def build_default_plan(self, raw_command: str) -> dict:
        return {
            'kind': 'remote_command',
            'command': raw_command,
            'command_type': COMMAND_TYPE_COMMAND,
            'extra': None,
        }

    def build_argument_command_plan(self, raw_command: str) -> dict:
        payload = self.parse_argument_command(raw_command)
        return {
            'kind': 'remote_command',
            'command': raw_command,
            'command_type': COMMAND_TYPE_ACMD,
            'extra': payload,
        }

    def build_script_plan(self, script_text: str, script_args_extra) -> dict:
        return {
            'kind': 'remote_command',
            'command': script_text,
            'command_type': COMMAND_TYPE_SCRIPT,
            'extra': script_args_extra,
        }


    def _wrap_alias_executor(self, alias_plan: dict):
        remote_executor = self.plan_executor(alias_plan)
        callback = self.alias_resolved_callback

        def runner():
            if callable(callback):
                for item in callback(alias_plan):
                    yield item

            for item in remote_executor():
                yield item

        return runner

    def _resolve_alias_command(self, name, arg):
        try:
            plan = self.build_alias_plan(name, arg)
            if not plan:
                return None
            return self._wrap_alias_executor(plan)
        except Exception as e:
            return self._wrap_error(e)

    def _resolve_default_command(self, raw_command):
        plan = self.build_default_plan(raw_command)
        return self.plan_executor(plan)

    def _resolve_argument_command(self, raw_command):
        plan = self.build_argument_command_plan(raw_command)
        return self.plan_executor(plan)

    def resolve(self, raw_command: str, name: str, arg: str):
        if self.is_argument_command(raw_command):
            return self._resolve_argument_command(raw_command)

        alias_handler = self._resolve_alias_command(name, arg)
        if alias_handler:
            return alias_handler

        return self._resolve_default_command(raw_command)
