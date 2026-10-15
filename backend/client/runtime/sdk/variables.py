"""在 Script 中读取 Client 动态变量，复用普通命令的变量解析规则。"""

from types import SimpleNamespace

from client.commands.runtime.command_variable_resolver import CommandVariableResolver
from client.runtime.sdk import context


def _resolver() -> CommandVariableResolver:
    owner = context.get_command_owner()
    runtime = getattr(owner, '_command_runtime', None) if owner is not None else None
    shared = getattr(runtime, 'command_variable_resolver', None)
    if shared is not None:
        return shared

    script_context = context.get_script_context()
    return CommandVariableResolver(
        SimpleNamespace(client_id=context.client_id()),
        rch_overrides=script_context.get('__rch_variables__'),
    )


def get(name: str) -> str:
    """读取一项变量，例如 get('rch:launch_command') 或 get('env:HOME')。"""
    key = str(name or '').strip()
    template = '${' + key + '}'
    if not CommandVariableResolver.VARIABLE_PATTERN.fullmatch(template):
        raise ValueError('Variable name must be namespace:name (rch, env, or path)')
    return _resolver().resolve(template, command_id=context.command_id())


def expand(text: str) -> str:
    """在字符串中展开 ${rch:*}、${env:*}、${path:*}。"""
    return _resolver().resolve(text, command_id=context.command_id())
