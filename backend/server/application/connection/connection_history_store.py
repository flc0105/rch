import threading
from datetime import datetime


from core.utils.datetime_utils import parse_iso_datetime
from core.utils.json_utils import compact_json_dumps, json_loads_dict
class ConnectionHistoryStore:
    """SQLite-backed machine/client connection lifecycle history."""

    SCHEMA_VERSION = 1

    SNAPSHOT_FIELDS = (
        'machine_id', 'client_id', 'hostname', 'addr', 'os_type', 'os_alias', 'os_ver',
        'os_name', 'os_full', 'arch', 'manufacturer', 'model', 'integrity', 'cwd',
        'build_version', 'python_ver', 'process_id', 'launch_command', 'username',
        'process_name', 'http_transfer_mode', 'python_execution_mode',
        'remote_watchdog_enabled', 'local_watchdog_enabled',
    )

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat()

    def _to_ms(self, value: str) -> int:
        parsed = parse_iso_datetime(value)
        return int(parsed.timestamp() * 1000) if parsed is not None else 0

    def _build_snapshot(self, connection: dict, previous: dict | None = None) -> dict:
        previous = previous if isinstance(previous, dict) else {}
        result = dict(previous)
        for field in self.SNAPSHOT_FIELDS:
            value = connection.get(field)
            if value is None:
                continue
            if isinstance(value, str) and not value and field in result:
                continue
            result[field] = value
        last_seen_at = str(connection.get('last_seen_at') or '').strip()
        if last_seen_at:
            result['last_seen_at'] = last_seen_at
        return result

    def _row_to_session(self, row, *, now_iso: str = '') -> dict:
        snapshot = json_loads_dict(row['snapshot_json'])
        result = dict(snapshot)
        result.update({
            'machine_id': row['machine_id'],
            'client_id': row['client_id'],
            'connected_at': row['connected_at'],
            'disconnected_at': row['disconnected_at'],
            'last_seen_at': row['last_seen_at'],
            'duration_ms': int(row['duration_ms'] or 0),
            'connection_state': row['connection_state'],
            'disconnect_reason': row['disconnect_reason'],
            'tracking_source': row['tracking_source'] or 'connection_lifecycle',
            'commands': [],
        })
        if not str(result.get('disconnected_at') or '').strip():
            result['connection_state'] = 'online'
            start = parse_iso_datetime(result.get('connected_at'))
            end = parse_iso_datetime(now_iso or self._now_iso())
            if start is not None and end is not None:
                result['duration_ms'] = max(int((end - start).total_seconds() * 1000), 0)
        return result

    def _record_connected_tx(self, conn, connection: dict):
        machine_id = str((connection or {}).get('machine_id') or '').strip()
        client_id = str((connection or {}).get('client_id') or '').strip()
        if not machine_id or not client_id:
            return

        connected_at = str(connection.get('connected_at') or self._now_iso()).strip()
        existing = conn.execute(
            'SELECT * FROM connection_sessions WHERE machine_id = ? AND client_id = ?',
            (machine_id, client_id),
        ).fetchone()
        previous_snapshot = json_loads_dict(existing['snapshot_json']) if existing else {}
        snapshot = self._build_snapshot(connection, previous_snapshot)
        last_seen_at = str(connection.get('last_seen_at') or connected_at).strip()

        if existing is None:
            conn.execute(
                '''
                INSERT INTO connection_sessions(
                    machine_id, client_id, connected_at, connected_at_ms, disconnected_at,
                    disconnected_at_ms, last_seen_at, duration_ms, connection_state,
                    disconnect_reason, tracking_source, snapshot_json
                ) VALUES (?, ?, ?, ?, '', 0, ?, 0, 'online', '', 'connection_lifecycle', ?)
                ''',
                (machine_id, client_id, connected_at, self._to_ms(connected_at), last_seen_at, compact_json_dumps(snapshot or {})),
            )
            return

        original_connected_at = str(existing['connected_at'] or connected_at).strip()
        conn.execute(
            '''
            UPDATE connection_sessions SET
                connected_at = ?, connected_at_ms = ?, disconnected_at = '', disconnected_at_ms = 0,
                last_seen_at = ?, duration_ms = 0, connection_state = 'online', disconnect_reason = '',
                snapshot_json = ?
            WHERE machine_id = ? AND client_id = ?
            ''',
            (
                original_connected_at, self._to_ms(original_connected_at), last_seen_at,
                compact_json_dumps(snapshot or {}), machine_id, client_id,
            ),
        )

    def record_connected(self, connection: dict):
        with self._lock, self.database.transaction() as conn:
            self._record_connected_tx(conn, connection)

    def record_heartbeat(self, connection: dict):
        machine_id = str((connection or {}).get('machine_id') or '').strip()
        client_id = str((connection or {}).get('client_id') or '').strip()
        if not machine_id or not client_id:
            return

        with self._lock, self.database.transaction() as conn:
            row = conn.execute(
                'SELECT * FROM connection_sessions WHERE machine_id = ? AND client_id = ?',
                (machine_id, client_id),
            ).fetchone()
            if row is None:
                self._record_connected_tx(conn, connection)
                return

            snapshot = self._build_snapshot(connection, json_loads_dict(row['snapshot_json']))
            last_seen_at = str(connection.get('last_seen_at') or row['last_seen_at'] or '').strip()
            disconnected_at = str(row['disconnected_at'] or '').strip()
            duration_ms = int(row['duration_ms'] or 0)
            state = row['connection_state']
            if not disconnected_at:
                state = 'online'
                start = parse_iso_datetime(row['connected_at'])
                end = parse_iso_datetime(self._now_iso())
                if start is not None and end is not None:
                    duration_ms = max(int((end - start).total_seconds() * 1000), 0)

            conn.execute(
                '''UPDATE connection_sessions SET last_seen_at = ?, duration_ms = ?, connection_state = ?, snapshot_json = ?
                   WHERE machine_id = ? AND client_id = ?''',
                (last_seen_at, duration_ms, state, compact_json_dumps(snapshot or {}), machine_id, client_id),
            )

    def reconcile_active_sessions(self, machine_id: str, active_client_ids: set[str]):
        machine_id_text = str(machine_id or '').strip()
        if not machine_id_text:
            return
        active_ids = {str(value or '').strip() for value in active_client_ids or set() if str(value or '').strip()}

        with self._lock, self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM connection_sessions WHERE machine_id = ? AND disconnected_at = ''",
                (machine_id_text,),
            ).fetchall()
            for row in rows:
                if str(row['client_id'] or '').strip() in active_ids:
                    continue
                disconnected_at = str(row['last_seen_at'] or row['connected_at'] or self._now_iso()).strip()
                start = parse_iso_datetime(row['connected_at'])
                end = parse_iso_datetime(disconnected_at)
                duration_ms = max(int((end - start).total_seconds() * 1000), 0) if start and end else 0
                conn.execute(
                    '''UPDATE connection_sessions SET disconnected_at = ?, disconnected_at_ms = ?, duration_ms = ?,
                       connection_state = 'interrupted', disconnect_reason = 'server_interrupted'
                       WHERE machine_id = ? AND client_id = ?''',
                    (disconnected_at, self._to_ms(disconnected_at), duration_ms, machine_id_text, row['client_id']),
                )

    def record_disconnected(self, connection: dict):
        machine_id = str((connection or {}).get('machine_id') or '').strip()
        client_id = str((connection or {}).get('client_id') or '').strip()
        if not machine_id or not client_id:
            return

        disconnected_at = str(connection.get('disconnected_at') or self._now_iso()).strip()
        with self._lock, self.database.transaction() as conn:
            row = conn.execute(
                'SELECT * FROM connection_sessions WHERE machine_id = ? AND client_id = ?',
                (machine_id, client_id),
            ).fetchone()
            if row is None:
                self._record_connected_tx(conn, connection)
                row = conn.execute(
                    'SELECT * FROM connection_sessions WHERE machine_id = ? AND client_id = ?',
                    (machine_id, client_id),
                ).fetchone()

            snapshot = self._build_snapshot(connection, json_loads_dict(row['snapshot_json']))
            start = parse_iso_datetime(row['connected_at'])
            end = parse_iso_datetime(disconnected_at)
            duration_ms = max(int((end - start).total_seconds() * 1000), 0) if start and end else 0
            last_seen_at = str(connection.get('last_seen_at') or row['last_seen_at'] or '').strip()
            conn.execute(
                '''
                UPDATE connection_sessions SET
                    disconnected_at = ?, disconnected_at_ms = ?, last_seen_at = ?, duration_ms = ?,
                    connection_state = 'offline', disconnect_reason = 'disconnected', snapshot_json = ?
                WHERE machine_id = ? AND client_id = ?
                ''',
                (
                    disconnected_at, self._to_ms(disconnected_at), last_seen_at, duration_ms,
                    compact_json_dumps(snapshot or {}), machine_id, client_id,
                ),
            )

    def get_history(self, machine_id: str) -> dict:
        machine_id_text = str(machine_id or '').strip()
        if not machine_id_text:
            return {
                'schema_version': self.SCHEMA_VERSION,
                'machine_id': '',
                'tracking_started_at': '',
                'sessions': [],
            }

        with self._lock:
            rows = self.database.connection().execute(
                '''SELECT * FROM connection_sessions WHERE machine_id = ?
                   ORDER BY connected_at_ms DESC, client_id DESC''',
                (machine_id_text,),
            ).fetchall()
            now_iso = self._now_iso()
            sessions = [self._row_to_session(row, now_iso=now_iso) for row in rows]
            tracking_started_at = min(
                (str(row['connected_at'] or '') for row in rows if str(row['connected_at'] or '')),
                default='',
            )
            return {
                'schema_version': self.SCHEMA_VERSION,
                'machine_id': machine_id_text,
                'tracking_started_at': tracking_started_at,
                'sessions': sessions,
            }
