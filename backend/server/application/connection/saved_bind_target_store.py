"""Structured Bind dial targets persisted as individual SQLite records."""
import threading
import uuid
from datetime import datetime

from server.application.connection.bind_web_endpoint import validate_web_origin
from server.runtime.bind_connector import BindConnector


class SavedBindTargetStore:
    """Endpoint identity stays independent of the last Client or machine ID."""

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()

    def list_targets(self):
        with self._lock:
            rows = self.database.connection().execute(
                'SELECT * FROM saved_bind_targets ORDER BY updated_at DESC, target_id ASC'
            ).fetchall()
            return [dict(row) for row in rows]

    def save(self, host, port, server_web_base_url, *, name='', session=None, target_id=''):
        host, port = BindConnector._endpoint(host, port)
        url = validate_web_origin(server_web_base_url)
        if not url:
            raise ValueError('Server Web URL is required')
        name = str(name or '').strip()
        if len(name) > 128:
            raise ValueError('Connection name is too long')
        now = datetime.now().isoformat()
        with self._lock, self.database.transaction() as conn:
            existing = conn.execute(
                'SELECT * FROM saved_bind_targets WHERE target_id = ?', (target_id,)
            ).fetchone() if target_id else None
            if target_id and existing is None:
                raise ValueError('Saved connection not found')
            duplicate = conn.execute(
                'SELECT * FROM saved_bind_targets WHERE host = ? AND port = ?', (host, port)
            ).fetchone()
            if existing is not None and duplicate is not None and existing['target_id'] != duplicate['target_id']:
                raise ValueError('A saved connection already uses this address')
            selected = existing if existing is not None else duplicate
            identifier = selected['target_id'] if selected is not None else uuid.uuid4().hex
            # A successful Connect must not erase an existing user-supplied name.
            final_name = name if existing is not None or selected is None or name else selected['name']
            if selected is None:
                conn.execute('''INSERT INTO saved_bind_targets
                    (target_id, host, port, server_web_base_url, name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (identifier, host, port, url, final_name, now, now))
            else:
                conn.execute('''UPDATE saved_bind_targets
                    SET host=?, port=?, server_web_base_url=?, name=?, updated_at=?
                    WHERE target_id=?''',
                    (host, port, url, final_name, now, identifier))
            if session is not None:
                info = session.session_info
                conn.execute('''UPDATE saved_bind_targets SET
                    last_client_id=?, machine_id=?, hostname=?, os_type=?, os_ver=?,
                    integrity=?, last_seen_at=? WHERE target_id=?''',
                    (str(info.client_id or ''), str(info.machine_id or ''),
                     str(info.hostname or ''), str(info.os_type or ''),
                     str(info.os_ver or ''), str(info.integrity or ''), now, identifier))
            return dict(conn.execute('SELECT * FROM saved_bind_targets WHERE target_id=?',
                                     (identifier,)).fetchone())

    def remove(self, target_id):
        with self._lock, self.database.transaction() as conn:
            cursor = conn.execute('DELETE FROM saved_bind_targets WHERE target_id=?', (target_id,))
            if cursor.rowcount != 1:
                raise ValueError('Saved connection not found')
            return {'target_id': target_id}
