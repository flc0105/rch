import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime


class NotificationHistoryStore:
    """Server-side durable Notification Center history in rch.db."""

    VERSION = 1

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()

    @staticmethod
    def _normalize_string(value, max_length: int = 0) -> str:
        text = str(value or '').strip()
        return text[:max_length] if max_length > 0 else text

    @staticmethod
    def _shown_at_ms(value: str) -> int:
        text = str(value or '').strip()
        if not text:
            return int(time.time() * 1000)
        try:
            normalized = text[:-1] + '+00:00' if text.endswith('Z') else text
            return int(datetime.fromisoformat(normalized).timestamp() * 1000)
        except Exception:
            return int(time.time() * 1000)

    @staticmethod
    def _json_dumps(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    @staticmethod
    def _json_loads(value, default):
        try:
            parsed = json.loads(value or '')
            return parsed if isinstance(parsed, type(default)) else default
        except Exception:
            return default

    def _normalize_notification(self, payload: dict, *, allow_missing_event_id: bool = False) -> dict:
        source = payload if isinstance(payload, dict) else {}
        title = self._normalize_string(source.get('title'), 300)
        message = self._normalize_string(source.get('message'), 5000)
        if not title:
            raise ValueError('Notification title is required')

        notification_id = self._normalize_string(source.get('id'), 200) or uuid.uuid4().hex
        event_id = self._normalize_string(source.get('event_id'), 200)
        if not event_id and not allow_missing_event_id:
            event_id = ''
        notification_type = self._normalize_string(source.get('type'), 32).lower()
        if notification_type not in {'success', 'warning', 'error', 'info'}:
            notification_type = 'info'

        context = source.get('context') if isinstance(source.get('context'), dict) else {}
        actions = source.get('actions') if isinstance(source.get('actions'), list) else []
        normalized_actions = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_type = self._normalize_string(action.get('type'), 64)
            label = self._normalize_string(action.get('label'), 120)
            if not action_type or not label:
                continue
            normalized_actions.append({
                'id': self._normalize_string(action.get('id'), 120),
                'type': action_type,
                'label': label,
                'url': self._normalize_string(action.get('url'), 2000),
            })

        return {
            'id': notification_id,
            'event_id': event_id,
            'notification_key': self._normalize_string(source.get('notification_key'), 120),
            'type': notification_type,
            'title': title,
            'message': message,
            'shown_at': self._normalize_string(source.get('shown_at'), 80),
            'context': context,
            'actions': normalized_actions,
        }

    def _row_to_notification(self, row) -> dict:
        return {
            'id': row['id'],
            'event_id': row['event_id'] or '',
            'notification_key': row['notification_key'],
            'type': row['type'],
            'title': row['title'],
            'message': row['message'],
            'shown_at': row['shown_at'],
            'context': self._json_loads(row['context_json'], {}),
            'actions': self._json_loads(row['actions_json'], []),
        }

    def get_history(self) -> dict:
        with self._lock:
            rows = self.database.connection().execute(
                'SELECT * FROM notifications ORDER BY shown_at_ms DESC, id DESC'
            ).fetchall()
            return {
                'version': self.VERSION,
                'notifications': [self._row_to_notification(row) for row in rows],
            }

    def get_notifications_after(self, notification_id: str) -> dict:
        """Return notifications inserted after a durable SSE cursor.

        SQLite rowid is used only as the local insertion-order cursor. The public
        SSE cursor remains the notification id, so clients never depend on the
        database implementation detail.
        """
        normalized_id = self._normalize_string(notification_id, 200)
        if not normalized_id:
            return {'cursor_found': False, 'notifications': []}

        with self._lock:
            conn = self.database.connection()
            cursor_row = conn.execute(
                'SELECT rowid AS notification_rowid FROM notifications WHERE id = ?',
                (normalized_id,),
            ).fetchone()
            if cursor_row is None:
                return {'cursor_found': False, 'notifications': []}

            rows = conn.execute(
                'SELECT * FROM notifications WHERE rowid > ? ORDER BY rowid ASC',
                (int(cursor_row['notification_rowid']),),
            ).fetchall()
            return {
                'cursor_found': True,
                'notifications': [self._row_to_notification(row) for row in rows],
            }

    def add_notification(self, payload: dict) -> tuple[dict, bool]:
        notification = self._normalize_notification(payload)
        event_id = notification.get('event_id') or ''

        with self._lock:
            conn = self.database.connection()
            if event_id:
                existing = conn.execute(
                    'SELECT * FROM notifications WHERE event_id = ?',
                    (event_id,),
                ).fetchone()
                if existing is not None:
                    return self._row_to_notification(existing), False

            try:
                conn.execute(
                    '''
                    INSERT INTO notifications(
                        id, event_id, notification_key, type, title, message, shown_at, shown_at_ms,
                        context_json, actions_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        notification['id'], event_id or None, notification['notification_key'], notification['type'],
                        notification['title'], notification['message'], notification['shown_at'],
                        self._shown_at_ms(notification['shown_at']), self._json_dumps(notification['context']),
                        self._json_dumps(notification['actions']),
                    ),
                )
            except sqlite3.IntegrityError:
                if event_id:
                    existing = conn.execute(
                        'SELECT * FROM notifications WHERE event_id = ?',
                        (event_id,),
                    ).fetchone()
                    if existing is not None:
                        return self._row_to_notification(existing), False
                raise

            return notification, True

    def delete_notification(self, notification_id: str) -> bool:
        normalized_id = str(notification_id or '').strip()
        if not normalized_id:
            raise ValueError('Notification id is required')
        with self._lock:
            cursor = self.database.connection().execute(
                'DELETE FROM notifications WHERE id = ?',
                (normalized_id,),
            )
            return cursor.rowcount > 0

    def clear_history(self) -> int:
        with self._lock, self.database.transaction() as conn:
            row = conn.execute('SELECT COUNT(*) FROM notifications').fetchone()
            removed_count = int(row[0] if row else 0)
            conn.execute('DELETE FROM notifications')
            return removed_count

    def delete_notifications(self, notification_ids) -> dict:
        normalized_ids = {
            str(value or '').strip()
            for value in (notification_ids or [])
            if str(value or '').strip()
        }
        with self._lock:
            conn = self.database.connection()
            if not normalized_ids:
                row = conn.execute('SELECT COUNT(*) FROM notifications').fetchone()
                return {'removed': [], 'remaining_count': int(row[0] if row else 0)}

            placeholders = ','.join('?' for _ in normalized_ids)
            with self.database.transaction() as tx:
                rows = tx.execute(
                    f'SELECT * FROM notifications WHERE id IN ({placeholders})',
                    tuple(normalized_ids),
                ).fetchall()
                removed = [self._row_to_notification(row) for row in rows]
                if removed:
                    tx.execute(
                        f'DELETE FROM notifications WHERE id IN ({placeholders})',
                        tuple(normalized_ids),
                    )
                remaining = tx.execute('SELECT COUNT(*) FROM notifications').fetchone()
                return {
                    'removed': removed,
                    'remaining_count': int(remaining[0] if remaining else 0),
                }
