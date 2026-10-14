import hashlib
import secrets
import threading
from datetime import datetime, timedelta

from server.application.auth.script_grant_policy import ScriptGrantPolicy


SCRIPT_GRANT_REQUEST_KEY = '__script_grant_request__'
SCRIPT_GRANT_TOKEN_KEY = '__script_grant__'
SCRIPT_GRANT_HEADER = 'X-Script-Grant-Token'


class ScriptGrantService:
    """
    Script SDK 临时授权服务。

    职责：
    - 签发单次脚本执行使用的临时 token
    - 保存 grant 与 command/client 的绑定关系
    - 校验 token 生命周期、使用次数、scope 与 Web API URL

    注意：
    - 只做 API URL 级别授权
    - 不查询 artifact / keychain 等业务数据
    - 不判断 artifact_id / artifact_type 等资源级规则
    """

    DEFAULT_TTL_SECONDS = 300
    DEFAULT_MAX_USES = 100

    def __init__(self, *, policy=None, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                 max_uses: int = DEFAULT_MAX_USES):
        self.policy = policy or ScriptGrantPolicy()
        self.ttl_seconds = int(ttl_seconds or self.DEFAULT_TTL_SECONDS)
        self.max_uses = int(max_uses or self.DEFAULT_MAX_USES)
        self._lock = threading.RLock()
        self._grants_by_hash = {}
        self._token_hash_by_command = {}

    def _now(self) -> datetime:
        return datetime.now()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()

    def _safe_text(self, value) -> str:
        return str(value or '').strip()

    def _normalize_grants(self, raw_grants) -> list[str]:
        if not isinstance(raw_grants, list):
            return []

        result = []
        seen = set()
        for item in raw_grants:
            if not isinstance(item, str):
                continue
            scope = self._safe_text(item)
            if not scope or scope in seen:
                continue
            if not self.policy.is_supported_scope(scope):
                continue
            seen.add(scope)
            result.append(scope)
        return result

    def _get_session_identity(self, session) -> dict:
        info = getattr(session, 'session_info', None)
        return {
            'client_id': getattr(info, 'client_id', '') or '',
            'machine_id': getattr(info, 'machine_id', '') or '',
            'hostname': getattr(info, 'hostname', '') or '',
        }

    def issue_script_grant(self, *, session, command_id, grant_request) -> dict:
        request_payload = grant_request if isinstance(grant_request, dict) else {}
        scopes = self._normalize_grants(request_payload.get('api_grants'))
        if not scopes:
            return {}

        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        now = self._now()
        ttl_seconds = int(request_payload.get('ttl_seconds') or self.ttl_seconds)
        if ttl_seconds <= 0 or ttl_seconds > self.ttl_seconds:
            ttl_seconds = self.ttl_seconds

        max_uses = int(request_payload.get('max_uses') or self.max_uses)
        if max_uses <= 0 or max_uses > self.max_uses:
            max_uses = self.max_uses

        identity = self._get_session_identity(session)
        grant = {
            'grant_id': secrets.token_hex(12),
            'token_hash': token_hash,
            'client_id': identity.get('client_id', ''),
            'machine_id': identity.get('machine_id', ''),
            'hostname': identity.get('hostname', ''),
            'command_id': command_id,
            'script_name': self._safe_text(request_payload.get('script_name')),
            'api_grants': scopes,
            'created_at': now,
            'expires_at': now + timedelta(seconds=ttl_seconds),
            'max_uses': max_uses,
            'used_count': 0,
            'revoked': False,
        }

        with self._lock:
            self.cleanup_expired(now=now)
            self._grants_by_hash[token_hash] = grant
            self._token_hash_by_command[(identity.get('client_id', ''), command_id)] = token_hash

        return {
            'token': token,
            'expires_at': grant.get('expires_at').isoformat(),
            'scopes': list(scopes),
            'script_name': grant.get('script_name', ''),
        }

    def cleanup_expired(self, *, now=None):
        current = now or self._now()
        expired_hashes = []
        for token_hash, grant in list(self._grants_by_hash.items()):
            if grant.get('revoked') or grant.get('expires_at') <= current:
                expired_hashes.append(token_hash)

        for token_hash in expired_hashes:
            grant = self._grants_by_hash.pop(token_hash, None)
            if isinstance(grant, dict):
                self._token_hash_by_command.pop((grant.get('client_id', ''), grant.get('command_id')), None)

    def revoke_by_command(self, *, client_id: str = '', command_id=None):
        key = (self._safe_text(client_id), command_id)
        with self._lock:
            token_hash = self._token_hash_by_command.pop(key, None)
            if token_hash:
                grant = self._grants_by_hash.get(token_hash)
                if isinstance(grant, dict):
                    grant['revoked'] = True
                self._grants_by_hash.pop(token_hash, None)

    def revoke_by_client(self, client_id: str):
        target_client_id = self._safe_text(client_id)
        if not target_client_id:
            return
        with self._lock:
            for token_hash, grant in list(self._grants_by_hash.items()):
                if grant.get('client_id') != target_client_id:
                    continue
                grant['revoked'] = True
                self._grants_by_hash.pop(token_hash, None)
                self._token_hash_by_command.pop((grant.get('client_id', ''), grant.get('command_id')), None)

    def _find_grant(self, token: str) -> dict | None:
        token_hash = self._hash_token(token)
        now = self._now()
        with self._lock:
            self.cleanup_expired(now=now)
            grant = self._grants_by_hash.get(token_hash)
            if not isinstance(grant, dict):
                return None
            if grant.get('revoked') or grant.get('expires_at') <= now:
                return None
            if int(grant.get('used_count') or 0) >= int(grant.get('max_uses') or 0):
                return None
            return grant

    def _get_header_value(self, headers, name: str) -> str:
        if not headers:
            return ''
        try:
            return self._safe_text(headers.get(name))
        except Exception:
            return ''

    def _has_scope(self, grant: dict, scope: str) -> bool:
        return scope in set(grant.get('api_grants') or [])

    def _increase_used_count(self, grant: dict):
        with self._lock:
            token_hash = grant.get('token_hash')
            stored = self._grants_by_hash.get(token_hash)
            if stored is grant:
                stored['used_count'] = int(stored.get('used_count') or 0) + 1

    def get_interaction_identity(self, token: str) -> dict | None:
        """Return only identity of a valid interaction grant; never expose token."""
        grant = self._find_grant(token) if token else None
        if not grant or not self._has_scope(grant, 'interactions:request'):
            return None
        return {'client_id': grant['client_id'], 'command_id': grant['command_id']}

    def authorize_request(self, *, method: str, path: str, headers=None) -> bool:
        scope = self.policy.match_request_scope(method, path)
        if not scope:
            return False

        token = self._get_header_value(headers, SCRIPT_GRANT_HEADER)
        if not token:
            return False

        grant = self._find_grant(token)
        if grant is None or not self._has_scope(grant, scope):
            return False

        self._increase_used_count(grant)
        return True
