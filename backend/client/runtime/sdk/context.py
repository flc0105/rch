import platform as _platform
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptSdkRuntimeContext:
    """
    Script SDK 当前执行上下文。

    只保存脚本运行期需要的轻量对象：
    - command_owner：当前平台命令实例，inproc 模式可复用既有命令能力
    - kwargs：server script 参数
    - script_context：CommandExecutionMixin 注入的 __context__
    """

    command_owner: Any = None
    kwargs: dict = field(default_factory=dict)
    script_context: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.script_context.get(key, default)


_current_context: ContextVar[ScriptSdkRuntimeContext | None] = ContextVar(
    'script_sdk_runtime_context',
    default=None,
)


def _safe_dict(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _detect_machine_identity() -> dict:
    try:
        from core.device.machine_identity import build_machine_identity_payload

        payload = build_machine_identity_payload()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _detect_machine_components() -> dict:
    try:
        from core.device.machine_identity import _detect_machine_identity_components

        payload = _detect_machine_identity_components()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _detect_platform_info() -> dict:
    try:
        from core.platform.platform_identity import detect_platform_info

        info = detect_platform_info()
        return {
            'alias': _safe_text(getattr(info, 'alias', '')),
            'display_name': _safe_text(getattr(info, 'display_name', '')),
            'system_name': _safe_text(getattr(info, 'system_name', '')),
        }
    except Exception:
        system_name = _safe_text(_platform.system()) or 'Unknown'
        return {
            'alias': system_name.lower(),
            'display_name': system_name,
            'system_name': system_name,
        }


def _detect_arch() -> str:
    try:
        from core.external_tools.platform import normalize_arch

        return _safe_text(normalize_arch(_platform.machine()))
    except Exception:
        return _safe_text(_platform.machine()).lower()


def get_current_context() -> ScriptSdkRuntimeContext:
    context = _current_context.get()
    if context is None:
        return ScriptSdkRuntimeContext()
    return context


def get_command_owner():
    return get_current_context().command_owner


def get_script_context() -> dict:
    return dict(get_current_context().script_context)


def get_client_id() -> str:
    return _safe_text(get_current_context().get('client_id', ''))


def get_command_id():
    command_id = get_current_context().get('command_id', '')
    return command_id if command_id != '' else None


def get_hostname() -> str:
    value = _safe_text(get_current_context().get('hostname', ''))
    return value or socket.gethostname()


def get_machine_id() -> str:
    value = _safe_text(get_current_context().get('machine_id', ''))
    if value:
        return value
    payload = _detect_machine_identity()
    return _safe_text(payload.get('machine_id_hash') or payload.get('machine_id'))


def get_os_alias() -> str:
    value = _safe_text(get_current_context().get('os_alias', ''))
    if value:
        return value
    value = _safe_text(get_current_context().get('platform', ''))
    if value:
        return value
    return _safe_text(_detect_platform_info().get('alias'))


def get_os_type() -> str:
    value = _safe_text(get_current_context().get('os_type', ''))
    if value:
        return value
    return _safe_text(_detect_platform_info().get('display_name'))


def get_os_ver() -> str:
    value = _safe_text(get_current_context().get('os_ver', ''))
    if value:
        return value
    machine_info = _detect_machine_components()
    return _safe_text(machine_info.get('os_version'))


# def get_platform() -> str:
#     return get_os_alias()


def get_arch() -> str:
    return _safe_text(get_current_context().get('arch', '')) or _detect_arch()


def get_script_name() -> str:
    context = get_current_context()
    value = _safe_text(context.get('script_name', ''))
    if value:
        return value
    return _safe_text(context.kwargs.get('script_name') or context.kwargs.get('name'))


def get_system_paths() -> dict:
    value = get_current_context().get('system_paths', {})
    if isinstance(value, dict) and value:
        return dict(value)
    try:
        from client.runtime.client_util import get_system_paths as detect_system_paths

        payload = detect_system_paths()
        return dict(payload) if isinstance(payload, dict) else {}
    except Exception:
        return {}


def client_id() -> str:
    return get_client_id()


def command_id():
    return get_command_id()


def hostname() -> str:
    return get_hostname()


def machine_id() -> str:
    return get_machine_id()


# def platform() -> str:
#     return get_platform()


def os_alias() -> str:
    return get_os_alias()


def os_type() -> str:
    return get_os_type()


def os_ver() -> str:
    return get_os_ver()


def arch() -> str:
    return get_arch()


def script_name() -> str:
    return get_script_name()


def system_paths() -> dict:
    return get_system_paths()


def get_script_grant() -> dict:
    value = get_current_context().get('script_grant', {})
    return dict(value) if isinstance(value, dict) else {}


def get_script_grant_token() -> str:
    return _safe_text(get_script_grant().get('token'))


@contextmanager
def use_script_sdk_context(command_owner=None, kwargs=None):
    payload = _safe_dict(kwargs)
    script_context = _safe_dict(payload.get('__context__'))
    token = _current_context.set(
        ScriptSdkRuntimeContext(
            command_owner=command_owner,
            kwargs=payload,
            script_context=script_context,
        )
    )
    try:
        yield
    finally:
        _current_context.reset(token)


def _iter_exported_command_names(command_owner):
    if command_owner is None:
        return []

    names = []
    for name in dir(command_owner):
        if not name or name.startswith('_'):
            continue
        try:
            func = getattr(command_owner, name)
        except Exception:
            continue
        if callable(func) and hasattr(func, 'help'):
            names.append(name)
    return sorted(set(names))


# def build_script_sdk_globals(command_owner=None, kwargs=None) -> dict:
#     """
#     构造注入到 server script 的 SDK 全局变量。
#     """
#     import sys
#
#     from client.runtime.sdk import artifact, command, keychains, workspace, xt
#
#     sdk_globals = {
#         'artifact': artifact,
#         'command': command,
#         'keychains': keychains,
#         'context': sys.modules[__name__],
#         'workspace': workspace,
#         'xt': xt,
#     }
#
#     for name in _iter_exported_command_names(command_owner):
#         if name in sdk_globals or name in {'kwargs', '__context__'}:
#             continue
#         sdk_globals[name] = command.build_client_command_function(name)
#
#     return sdk_globals


def build_script_sdk_globals(command_owner=None, kwargs=None) -> dict:
    """
    构造注入到 server script 的 SDK 全局变量。
    """
    import sys

    from client.runtime.sdk import artifact, command, events, keychains, workspace, xt

    sdk_globals = {
        'artifact': artifact,
        'command': command,
        'events': events,
        'keychains': keychains,
        'context': sys.modules[__name__],
        'workspace': workspace,
        'xt': xt,
    }

    import builtins

    builtin_names = set(dir(builtins))  # 如果命令名和内置方法冲突则不导入，比如set()

    for name in _iter_exported_command_names(command_owner):
        if name in sdk_globals or name in {'kwargs', '__context__'}:
            continue
        if name in builtin_names:
            continue
        sdk_globals[name] = command.build_client_command_function(name)

    return sdk_globals