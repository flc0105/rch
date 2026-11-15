from contextlib import contextmanager
import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptSdkRuntimeContext:
    """
    Script SDK 当前执行上下文。

    只保存脚本运行期需要的轻量对象：
    - execution_owner：单次执行能力对象，inproc 模式可使用 SDK
    - kwargs：server script 参数
    - script_context：执行层注入的 __context__
    """

    execution_owner: Any = None
    emit_event: Any = None
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


def _get_local_identity():
    try:
        from core.device.local_identity import get_local_identity

        return get_local_identity()
    except Exception:
        return None


def get_current_context() -> ScriptSdkRuntimeContext:
    context = _current_context.get()
    if context is None:
        return ScriptSdkRuntimeContext()
    return context


def get_execution_owner():
    return get_current_context().execution_owner


def get_script_context() -> dict:
    return dict(get_current_context().script_context)


def get_client_id() -> str:
    return _safe_text(get_current_context().get('client_id', ''))


def get_command_id():
    command_id = get_current_context().get('command_id', '')
    return command_id if command_id != '' else None


def get_hostname() -> str:
    value = _safe_text(get_current_context().get('hostname', ''))
    identity = _get_local_identity()
    return _safe_text(getattr(identity, 'hostname', ''))


def get_machine_id() -> str:
    value = _safe_text(get_current_context().get('machine_id', ''))
    if value:
        return value
    identity = _get_local_identity()
    return _safe_text(getattr(identity, 'machine_id', ''))


def get_os_alias() -> str:
    value = _safe_text(get_current_context().get('os_alias', ''))
    if value:
        return value
    value = _safe_text(get_current_context().get('platform', ''))
    if value:
        return value
    identity = _get_local_identity()
    return _safe_text(getattr(identity, 'os_alias', ''))


def get_os_type() -> str:
    value = _safe_text(get_current_context().get('os_type', ''))
    if value:
        return value
    identity = _get_local_identity()
    return _safe_text(getattr(identity, 'os_type', ''))


def get_os_ver() -> str:
    value = _safe_text(get_current_context().get('os_ver', ''))
    if value:
        return value
    identity = _get_local_identity()
    return _safe_text(getattr(identity, 'os_version', ''))


# def get_platform() -> str:
#     return get_os_alias()


def get_arch() -> str:
    value = _safe_text(get_current_context().get('arch', ''))
    if value:
        return value
    identity = _get_local_identity()
    return _safe_text(getattr(identity, 'arch', ''))


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


def progress(message: str, *, level: str | None = None) -> None:
    """Emit a live Script progress event in either Python execution mode.

    Only explicitly levelled progress receives a terminal Output Marker.
    Ordinary print() and context.emit() remain text/structured chunks.
    """
    from core.utils.output_marker import OUTPUT_MARKERS
    if level is not None and level not in OUTPUT_MARKERS:
        raise ValueError('Invalid Script progress level')
    text = str(message)
    owner = get_execution_owner()
    if owner is not None and callable(getattr(owner, 'emit_progress', None)):
        owner.emit_progress(text, level=level)
        return
    channel = getattr(get_current_context().emit_event, 'progress', None)
    if callable(channel):
        channel(text, level=level)
        return
    print(text, flush=True)


def emit(data: dict | list) -> None:
    """Emit one structured Script output event in execution order.

    A JSON object or array is an output record, not a Script return value.
    """
    if not isinstance(data, (dict, list)):
        raise TypeError('Structured output requires a JSON object or array')
    # Validate/freeze now: callers cannot mutate the value after emission.
    validated = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
    sender = get_current_context().emit_event
    if not callable(sender):
        raise RuntimeError('Structured output requires an active Script output channel')
    sender(validated)


def confirm(message: str, *, title='Confirmation', timeout=90) -> bool:
    """Request opt-in Web approval; rejection or timeout returns False."""
    from client.runtime.sdk.interactions import confirm as request_confirmation
    return request_confirmation(message, title=title, timeout=timeout)


def select(message: str, options, *, title='Choose an option', timeout=90) -> str:
    """Choose an item from a fixed list via the shared Web execution interaction."""
    from client.runtime.sdk.interactions import select as request_selection
    return request_selection(message, options, title=title, timeout=timeout)


def ask(message: str, *, title='Input required', timeout=90, placeholder='', secret=False) -> str:
    """Request Web text input for the active inproc script."""
    from client.runtime.sdk.interactions import ask as request_input
    return request_input(message, title=title, timeout=timeout, placeholder=placeholder, secret=secret)


def approve_preview(message: str, preview: dict, *, title='Review execution plan', timeout=90) -> bool:
    """Show a structured preview and require explicit approval before continuing."""
    from client.runtime.sdk.interactions import approve_preview as request_preview
    return request_preview(message, preview, title=title, timeout=timeout)


def select_preview_rows(message: str, preview: dict, *, title='Review execution plan', timeout=90) -> list[str]:
    """Return selected row IDs after approval; cancellation raises."""
    from client.runtime.sdk.interactions import select_preview_rows as request_rows
    return request_rows(message, preview, title=title, timeout=timeout)


def get_client_session_token() -> str:
    """Connection-bound HTTP API credential, if a Client session is active."""
    token = _safe_text(get_current_context().get('client_session_token', ''))
    if token:
        return token
    owner = get_execution_owner()
    return _safe_text(getattr(getattr(owner, 'socket', None), 'client_session_token', ''))


@contextmanager
def use_script_sdk_context(execution_owner=None, kwargs=None, *, emit_event=None):
    payload = _safe_dict(kwargs)
    script_context = _safe_dict(payload.get('__context__'))
    if emit_event is None:
        emit_event = get_current_context().emit_event
    token = _current_context.set(
        ScriptSdkRuntimeContext(
            execution_owner=execution_owner,
            emit_event=emit_event,
            kwargs=payload,
            script_context=script_context,
        )
    )
    try:
        yield
    finally:
        _current_context.reset(token)


def _iter_exported_command_names(execution_owner):
    if execution_owner is None:
        return []

    provider = getattr(execution_owner, "sdk_command_names", None)
    if callable(provider):
        return provider()
    names = []
    for name in dir(execution_owner):
        if not name or name.startswith('_'):
            continue
        try:
            func = getattr(execution_owner, name)
        except Exception:
            continue
        if callable(func) and hasattr(func, 'help'):
            names.append(name)
    return sorted(set(names))


# def build_script_sdk_globals(execution_owner=None, kwargs=None) -> dict:
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
#     for name in _iter_exported_command_names(execution_owner):
#         if name in sdk_globals or name in {'kwargs', '__context__'}:
#             continue
#         sdk_globals[name] = command.build_client_command_function(name)
#
#     return sdk_globals


def build_script_sdk_globals(execution_owner=None, kwargs=None) -> dict:
    """
    构造注入到 server script 的 SDK 全局变量。
    """
    import sys

    from client.runtime.sdk import artifact, command, events, keychains, scripts, workspace, xt

    sdk_globals = {
        'artifact': artifact,
        'command': command,
        'events': events,
        'keychains': keychains,
        'scripts': scripts,
        'context': sys.modules[__name__],
        'workspace': workspace,
        'xt': xt,
    }

    import builtins

    builtin_names = set(dir(builtins))  # 如果命令名和内置方法冲突则不导入，比如set()

    for name in _iter_exported_command_names(execution_owner):
        if name in sdk_globals or name in {'kwargs', '__context__'}:
            continue
        if name in builtin_names:
            continue
        sdk_globals[name] = command.build_client_command_function(name)

    return sdk_globals