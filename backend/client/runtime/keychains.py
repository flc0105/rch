"""
Client-side helper for reading server-side Keychains from scripts.

Usage:
    from client.runtime.keychains import get_secret, get_login

    token = get_secret("github-token").getvalue()

    login = get_login("nas-admin")
    username = login.username
    password = login.password.getvalue()

说明：
- 这个工具只读取服务端 runtime/keychains 里的凭证。
- 第一版使用 allow_anonymous 的 resolve 接口，适合个人运维环境；当前已收口到 script grant 临时授权。
- SecretValue 默认打印为掩码，必须显式 .getvalue() 才返回真实值。
"""

import builtins
from dataclasses import dataclass
from typing import Any


SHARED_SCOPE = 'shared'
MACHINE_SCOPE = 'machine'
SHARED_MACHINE_ID = '__shared__'
KEYCHAINS_LIST_GRANT = 'keychains:list'
KEYCHAINS_RESOLVE_GRANT = 'keychains:resolve'
KEYCHAINS_CREATE_GRANT = 'keychains:create'


class KeychainError(RuntimeError):
    """Keychains helper 统一异常。"""
    pass


class SecretValue:
    """
    包装敏感值。

    避免 print()/repr() 时直接把明文打到日志里；
    脚本确实要使用明文时，显式调用 getvalue()。
    """

    def __init__(self, value: Any = ''):
        self._value = '' if value is None else str(value)

    def getvalue(self) -> str:
        return self._value

    def is_empty(self) -> bool:
        return self._value == ''

    def __bool__(self) -> bool:
        return bool(self._value)

    def __str__(self) -> str:
        return '********' if self._value else ''

    def __repr__(self) -> str:
        return 'SecretValue(********)' if self._value else 'SecretValue()'


@dataclass(frozen=True)
class LoginCredential:
    name: str
    username: str
    password: SecretValue
    site: str = ''
    note: str = ''
    machine_id: str = ''
    hostname: str = ''
    created_at: str = ''
    updated_at: str = ''


@dataclass(frozen=True)
class SecretCredential:
    name: str
    value: SecretValue
    note: str = ''
    machine_id: str = ''
    hostname: str = ''
    created_at: str = ''
    updated_at: str = ''


def _safe_text(value: Any) -> str:
    return '' if value is None else str(value).strip()


def _build_missing_grant_message(scope: str = KEYCHAINS_RESOLVE_GRANT) -> str:
    normalized_scope = _safe_text(scope) or KEYCHAINS_RESOLVE_GRANT
    return (
        f'Keychains access requires script grant: {normalized_scope}. '
        f'Add SCRIPT_METADATA["api_grants"] = ["{normalized_scope}"] to this script.'
    )


def _normalize_scope(scope: str) -> str:
    value = _safe_text(scope).lower() or MACHINE_SCOPE
    if value in (SHARED_SCOPE, SHARED_MACHINE_ID):
        return SHARED_SCOPE
    if value == MACHINE_SCOPE:
        return MACHINE_SCOPE
    raise ValueError('scope must be machine or shared')


def _get_current_machine_id() -> str:
    try:
        from core.device.local_identity import get_local_identity

        return _safe_text(get_local_identity().machine_id)
    except Exception as exc:
        raise KeychainError(f'Failed to detect current machine id: {exc}') from exc


def _resolve_machine_id(scope: str, machine_id: str = '') -> str:
    normalized_scope = _normalize_scope(scope)
    if normalized_scope == SHARED_SCOPE:
        return SHARED_MACHINE_ID

    explicit_machine_id = _safe_text(machine_id)
    if explicit_machine_id:
        return explicit_machine_id

    current_machine_id = _get_current_machine_id()
    if not current_machine_id:
        raise KeychainError('Current machine id is empty')
    return current_machine_id


def _normalize_public_keychain_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    return {
        'id': _safe_text(item.get('id') or item.get('cred_id')),
        'name': _safe_text(item.get('name')),
        'kind': _safe_text(item.get('kind')),
        'username': _safe_text(item.get('username')),
        'site': _safe_text(item.get('site')),
        'note': _safe_text(item.get('note')),
        'machine_id': _safe_text(item.get('machine_id')),
        'hostname': _safe_text(item.get('hostname')),
        'created_at': _safe_text(item.get('created_at')),
        'updated_at': _safe_text(item.get('updated_at')),
    }


def _list_keychain_items(*, scope: str = MACHINE_SCOPE) -> builtins.list[dict]:
    machine_id = _resolve_machine_id(scope)
    try:
        from client.http.client_api import ClientApiClient, ClientApiError

        data = ClientApiClient().get_data(
            '/api/keychains',
            params={'machine_id': machine_id},
            timeout=15,
        )
    except ImportError as exc:
        raise KeychainError('client.http.client_api is required to list keychains') from exc
    except ClientApiError as exc:
        message = str(exc) or 'Failed to list keychains'
        if message in {'Authentication required', 'Forbidden'}:
            raise KeychainError(_build_missing_grant_message(KEYCHAINS_LIST_GRANT)) from None
        raise KeychainError(message) from None
    except Exception as exc:
        # 其他异常保留原始原因，便于定位网络/序列化等非授权问题。
        raise KeychainError(str(exc) or 'Failed to list keychains') from exc

    if not isinstance(data, dict):
        raise KeychainError('Invalid keychain list response')

    items = data.get('items') or []
    if not isinstance(items, builtins.list):
        return []

    return [normalized for normalized in (_normalize_public_keychain_item(item) for item in items) if normalized]


def _request_keychain_item(name: str, *, kind: str = '', scope: str = MACHINE_SCOPE, machine_id: str = '') -> dict:
    normalized_name = _safe_text(name)
    if not normalized_name:
        raise ValueError('keychain name is required')

    normalized_kind = _safe_text(kind).lower()
    if normalized_kind and normalized_kind not in ('login', 'secret'):
        raise ValueError('kind must be login or secret')

    payload = {
        'name': normalized_name,
        'kind': normalized_kind,
        'scope': _normalize_scope(scope),
        'machine_id': _resolve_machine_id(scope, machine_id),
    }

    try:
        from client.http.client_api import ClientApiClient, ClientApiError

        data = ClientApiClient().post_data('/api/keychains/resolve', json=payload, timeout=15)
    except ImportError as exc:
        raise KeychainError('client.http.client_api is required to resolve keychains') from exc
    except ClientApiError as exc:
        message = str(exc) or 'Failed to resolve keychain'
        if message in {'Authentication required', 'Forbidden'}:
            raise KeychainError(_build_missing_grant_message(KEYCHAINS_RESOLVE_GRANT)) from None
        raise KeychainError(message) from None
    except Exception as exc:
        # 其他异常保留原始原因，便于定位网络/序列化等非授权问题。
        raise KeychainError(str(exc) or 'Failed to resolve keychain') from exc

    if not isinstance(data, dict):
        raise KeychainError('Invalid keychain resolve response')

    item = data.get('item')
    if not isinstance(item, dict):
        raise KeychainError('Keychain item missing in response')

    return item



def _create_keychain_item(payload: dict) -> dict:
    try:
        from client.http.client_api import ClientApiClient, ClientApiError

        data = ClientApiClient().post_data('/api/keychains', json=payload, timeout=15)
    except ImportError as exc:
        raise KeychainError('client.http.client_api is required to create keychains') from exc
    except ClientApiError as exc:
        message = str(exc) or 'Failed to create keychain'
        if message in {'Authentication required', 'Forbidden'}:
            raise KeychainError(_build_missing_grant_message(KEYCHAINS_CREATE_GRANT)) from None
        raise KeychainError(message) from None
    except Exception as exc:
        # 其他异常保留原始原因，便于定位网络/序列化等非授权问题。
        raise KeychainError(str(exc) or 'Failed to create keychain') from exc

    if not isinstance(data, dict):
        raise KeychainError('Invalid keychain create response')

    item = data.get('item')
    if not isinstance(item, dict):
        raise KeychainError('Keychain item missing in create response')

    return item

def _build_login_credential(item: dict) -> LoginCredential:
    if _safe_text(item.get('kind')).lower() != 'login':
        raise KeychainError(f'Keychain is not a login: {item.get("name") or ""}')

    return LoginCredential(
        name=_safe_text(item.get('name')),
        username=_safe_text(item.get('username')),
        password=SecretValue(item.get('secret_value')),
        site=_safe_text(item.get('site')),
        note=_safe_text(item.get('note')),
        machine_id=_safe_text(item.get('machine_id')),
        hostname=_safe_text(item.get('hostname')),
        created_at=_safe_text(item.get('created_at')),
        updated_at=_safe_text(item.get('updated_at')),
    )


def _build_secret_credential(item: dict) -> SecretCredential:
    if _safe_text(item.get('kind')).lower() != 'secret':
        raise KeychainError(f'Keychain is not a secret: {item.get("name") or ""}')

    return SecretCredential(
        name=_safe_text(item.get('name')),
        value=SecretValue(item.get('secret_value')),
        note=_safe_text(item.get('note')),
        machine_id=_safe_text(item.get('machine_id')),
        hostname=_safe_text(item.get('hostname')),
        created_at=_safe_text(item.get('created_at')),
        updated_at=_safe_text(item.get('updated_at')),
    )



def list(*, scope: str = MACHINE_SCOPE) -> builtins.list[dict]:
    """
    列出当前 machine 或 shared 下的凭证基础信息。

    只返回 metadata，不返回 secret_value。
    默认读取当前 machine_id；读取共享凭证时使用：
        keychains.list(scope='shared')
    """
    return _list_keychain_items(scope=scope)


def list_keychains(*, scope: str = MACHINE_SCOPE) -> builtins.list[dict]:
    return list(scope=scope)


def create_secret(
    name: str,
    value: Any = '',
    *,
    scope: str = MACHINE_SCOPE,
    note: str = '',
) -> SecretCredential:
    """
    创建 Secrets 类型凭证。

    默认写入当前 machine_id；写入共享凭证时使用：
        create_secret('xxx', 'value', scope='shared')
    """
    normalized_name = _safe_text(name)
    if not normalized_name:
        raise ValueError('keychain name is required')

    payload = {
        'name': normalized_name,
        'kind': 'secret',
        'secret_value': '' if value is None else str(value),
        'scope': _normalize_scope(scope),
        'machine_id': _resolve_machine_id(scope),
        'note': _safe_text(note),
    }
    return _build_secret_credential(_create_keychain_item(payload))


def create_login(
    name: str,
    username: str,
    password: Any = '',
    *,
    scope: str = MACHINE_SCOPE,
    site: str = '',
    note: str = '',
) -> LoginCredential:
    """
    创建 Logins 类型凭证。

    默认写入当前 machine_id；写入共享凭证时使用：
        create_login('xxx', 'user', 'password', scope='shared')
    """
    normalized_name = _safe_text(name)
    normalized_username = _safe_text(username)
    if not normalized_name:
        raise ValueError('keychain name is required')
    if not normalized_username:
        raise ValueError('username is required')

    payload = {
        'name': normalized_name,
        'kind': 'login',
        'username': normalized_username,
        'secret_value': '' if password is None else str(password),
        'scope': _normalize_scope(scope),
        'machine_id': _resolve_machine_id(scope),
        'site': _safe_text(site),
        'note': _safe_text(note),
    }
    return _build_login_credential(_create_keychain_item(payload))

def get_secret(name: str, *, scope: str = MACHINE_SCOPE, machine_id: str = '') -> SecretValue:
    """
    读取 Secrets 类型凭证的 value。

    默认读取当前 machine_id 下的凭证；读取共享凭证时使用：
        get_secret('xxx', scope='shared')
    """
    item = _request_keychain_item(name, kind='secret', scope=scope, machine_id=machine_id)
    return SecretValue(item.get('secret_value'))


def get_login(name: str, *, scope: str = MACHINE_SCOPE, machine_id: str = '') -> LoginCredential:
    """
    读取 Logins 类型凭证。

    返回对象字段：
        login.username
        login.password.getvalue()
    """
    item = _request_keychain_item(name, kind='login', scope=scope, machine_id=machine_id)
    return _build_login_credential(item)


def get_keychain(name: str, *, kind: str = '', scope: str = MACHINE_SCOPE, machine_id: str = ''):
    """
    通用读取入口。

    kind 为空时由服务端按 name 查找；返回 LoginCredential 或 SecretCredential。
    """
    item = _request_keychain_item(name, kind=kind, scope=scope, machine_id=machine_id)
    item_kind = _safe_text(item.get('kind')).lower()
    if item_kind == 'login':
        return _build_login_credential(item)
    if item_kind == 'secret':
        return _build_secret_credential(item)
    raise KeychainError(f'Unsupported keychain kind: {item_kind or "unknown"}')
