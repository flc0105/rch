import builtins
from urllib.parse import quote

from client.runtime.sdk import context



class ScriptSdkWorkspaceError(RuntimeError):
    """Script SDK workspace 统一异常。"""
    pass


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _current_client_id() -> str:
    client_id = context.client_id()
    if not client_id:
        raise ScriptSdkWorkspaceError('current client_id is empty')
    return client_id


def _request_workspace() -> dict:
    try:
        from client.http.client_api import ClientApiClient, ClientApiError

        client_id = quote(_current_client_id(), safe='')
        data = ClientApiClient().get_data(f'/api/connections/{client_id}/pinned_paths', timeout=15)
    except ImportError as exc:
        raise ScriptSdkWorkspaceError('client.http.client_api is required to read workspace') from exc
    except ClientApiError as exc:
        message = str(exc) or 'Failed to read workspace'
        if message in {'Authentication required', 'Forbidden'}:
            raise ScriptSdkWorkspaceError('Client Session Token authentication required') from None
        raise ScriptSdkWorkspaceError(message) from None
    except Exception as exc:
        raise ScriptSdkWorkspaceError(str(exc) or 'Failed to read workspace') from exc

    if not isinstance(data, dict):
        raise ScriptSdkWorkspaceError('Invalid workspace response')
    return data


def _system_path(name: str, default: str = '') -> str:
    value = system_paths().get(name)
    return _safe_text(value) or default


def list() -> builtins.list[dict]:
    """返回当前 client 所属 machine 的 pinned paths。"""
    items = _request_workspace().get('items') or []
    return items if isinstance(items, builtins.list) else []


def as_dict() -> dict[str, str]:
    """以 {display_name: path} 形式返回 pinned paths。"""
    result = {}
    for item in list():
        if not isinstance(item, dict):
            continue
        name = _safe_text(item.get('display_name') or item.get('name'))
        path = _safe_text(item.get('path'))
        if name and path:
            result[name] = path
    return result


def get(display_name: str, default: str = '') -> str:
    """按 display_name 获取 pinned path，找不到时返回 default。"""
    target = _safe_text(display_name)
    if not target:
        raise ValueError('display_name is required')
    for name, path in as_dict().items():
        if name == target:
            return path
    return default


def path(display_name: str, default: str = '') -> str:
    return get(display_name, default=default)


def system_paths() -> dict[str, str]:
    """返回脚本上下文中的当前 client 系统路径。"""
    result = {}
    for name, value in context.system_paths().items():
        key = _safe_text(name)
        path_value = _safe_text(value)
        if key and path_value:
            result[key] = path_value
    return result


def root(default: str = '') -> str:
    return _system_path('root', default=default)


def home(default: str = '') -> str:
    return _system_path('home', default=default)


def desktop(default: str = '') -> str:
    return _system_path('desktop', default=default)


def documents(default: str = '') -> str:
    return _system_path('documents', default=default)


def downloads(default: str = '') -> str:
    return _system_path('downloads', default=default)


def temp(default: str = '') -> str:
    return _system_path('temp', default=default)


def executable(default: str = '') -> str:
    return _system_path('executable', default=default)


def icloud(default: str = '') -> str:
    return _system_path('icloud', default=default)
