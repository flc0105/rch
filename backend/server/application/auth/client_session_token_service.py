"""One HTTP API credential for the lifetime of each connected Client session."""
import hashlib
import hmac
import secrets
import threading

from server.application.auth.client_api_policy import ClientApiPolicy
from core.protocol.client_api_auth import CLIENT_SESSION_TOKEN_HEADER


class ClientSessionTokenService:
    def __init__(self, policy=None):
        self.policy = policy or ClientApiPolicy()
        self._lock = threading.RLock()
        self._sessions = {}  # client_id -> (token_digest, session)

    @staticmethod
    def _digest(token):
        return hashlib.sha256(str(token or '').encode('utf-8')).digest()

    def issue(self, session):
        info = getattr(session, 'session_info', None)
        client_id = str(getattr(info, 'client_id', '') or '')
        if not client_id:
            raise ValueError('Client ID is required for a session token')
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[client_id] = (self._digest(token), session)
        return token

    def identify(self, token):
        if not token:
            return None
        digest = self._digest(token)
        with self._lock:
            for client_id, (stored, session) in self._sessions.items():
                if hmac.compare_digest(stored, digest):
                    info = getattr(session, 'session_info', None)
                    return {
                        'client_id': client_id,
                        'machine_id': str(getattr(info, 'machine_id', '') or ''),
                        'session': session,
                    }
        return None

    def revoke(self, session):
        client_id = str(getattr(getattr(session, 'session_info', None), 'client_id', '') or '')
        with self._lock:
            existing = self._sessions.get(client_id)
            if existing and existing[1] is session:
                self._sessions.pop(client_id, None)

    def authenticate(self, *, method, path, headers):
        token = str((headers or {}).get(CLIENT_SESSION_TOKEN_HEADER) or '').strip()
        if not self.policy.allows(method, path):
            return None
        identity = self.identify(token)
        if identity is None:
            return None
        if path.startswith('/api/connections/') and path.endswith('/pinned_paths'):
            target = path.split('/')[3]
            if target != identity['client_id']:
                return None
        return identity
