import threading
from datetime import datetime, timezone


from core.utils.datetime_utils import parse_iso_datetime
from core.utils.json_utils import compact_json_dumps, json_loads_dict
class ConnectionHistoryStore:
    """SQLite-backed machine/client connection lifecycle history."""

    SNAPSHOT_FIELDS = (
        'hostname', 'addr',
        'listener_id', 'listener_name', 'listener_protocol', 'listener_port',
        'os_name', 'os_ver', 'integrity',
        'build_version', 'python_ver', 'process_id', 'launch_command',
        'launch_mode', 'launch_source', 'username', 'process_name',
    )

    # Only fields consumed by Connection History are exposed in the session VO.
    SESSION_VIEW_FIELDS = (
        'addr', 'listener_name', 'os_name', 'os_ver', 'integrity',
        'build_version', 'process_id', 'launch_mode', 'launch_source',
        'username', 'process_name',
    )

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_utc(value: str):
        parsed = parse_iso_datetime(value)
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @classmethod
    def _elapsed_ms(cls, start_time: str, end_time: str) -> int:
        start = cls._parse_utc(start_time)
        end = cls._parse_utc(end_time)
        return max(int((end - start).total_seconds() * 1000), 0) if start and end else 0

    def _to_ms(self, value: str) -> int:
        parsed = self._parse_utc(value)
        return int(parsed.timestamp() * 1000) if parsed is not None else 0

    def _build_snapshot(self, connection: dict, previous: dict | None = None) -> dict:
        previous = previous if isinstance(previous, dict) else {}
        result = {field: previous[field] for field in self.SNAPSHOT_FIELDS if field in previous}
        for field in self.SNAPSHOT_FIELDS:
            value = connection.get(field)
            if value is None:
                continue
            if isinstance(value, str) and not value and field in result:
                continue
            result[field] = value
        return result

    def _row_to_session(self, row, *, now_iso: str = '') -> dict:
        snapshot = json_loads_dict(row['snapshot'])
        result = {field: snapshot.get(field) for field in self.SESSION_VIEW_FIELDS if field in snapshot}
        result.update({
            'machine_id': row['machine_id'],
            'client_id': row['client_id'],
            'connected_at': row['connected_at'],
            'disconnected_at': row['disconnected_at'],
            'last_seen_at': row['last_seen_at'],
            'duration_ms': int(row['duration_ms'] or 0),
            'termination_reason': row['termination_reason'],
            'termination_detail': json_loads_dict(row['termination_detail']),
        })
        if not str(result['disconnected_at'] or '').strip():
            result['duration_ms'] = self._elapsed_ms(result['connected_at'], now_iso or self._now_iso())
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
        previous_snapshot = json_loads_dict(existing['snapshot']) if existing else {}
        snapshot = self._build_snapshot(connection, previous_snapshot)
        last_seen_at = str(connection.get('last_seen_at') or connected_at).strip()

        if existing is None:
            conn.execute(
                '''
                INSERT INTO connection_sessions(
                    machine_id, client_id, connected_at, connected_at_ms, disconnected_at,
                    disconnected_at_ms, last_seen_at, duration_ms,
                    termination_reason, termination_detail, snapshot
                ) VALUES (?, ?, ?, ?, '', 0, ?, 0, '', '{}', ?)
                ''',
                (machine_id, client_id, connected_at, self._to_ms(connected_at), last_seen_at, compact_json_dumps(snapshot or {})),
            )
            return

        original_connected_at = str(existing['connected_at'] or connected_at).strip()
        conn.execute(
            '''
            UPDATE connection_sessions SET
                connected_at = ?, connected_at_ms = ?, disconnected_at = '', disconnected_at_ms = 0,
                last_seen_at = ?, duration_ms = 0,
                termination_reason = '', termination_detail = '{}', snapshot = ?
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

            snapshot = self._build_snapshot(connection, json_loads_dict(row['snapshot']))
            last_seen_at = str(connection.get('last_seen_at') or row['last_seen_at'] or '').strip()
            disconnected_at = str(row['disconnected_at'] or '').strip()
            duration_ms = int(row['duration_ms'] or 0)
            if not disconnected_at:
                duration_ms = self._elapsed_ms(row['connected_at'], self._now_iso())

            conn.execute(
                '''UPDATE connection_sessions SET last_seen_at = ?, duration_ms = ?, snapshot = ?
                   WHERE machine_id = ? AND client_id = ?''',
                (last_seen_at, duration_ms, compact_json_dumps(snapshot or {}), machine_id, client_id),
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
                duration_ms = self._elapsed_ms(row['connected_at'], disconnected_at)
                conn.execute(
                    '''UPDATE connection_sessions SET disconnected_at = ?, disconnected_at_ms = ?, duration_ms = ?,
                       termination_reason = ?
                       WHERE machine_id = ? AND client_id = ?''',
                    (disconnected_at, self._to_ms(disconnected_at), duration_ms, 'unexpected_disconnect',
                     machine_id_text, row['client_id']),
                )

    def record_disconnected(self, connection: dict, *, termination_reason: str = '', details: dict = None):
        machine_id = str((connection or {}).get('machine_id') or '').strip()
        client_id = str((connection or {}).get('client_id') or '').strip()
        if not machine_id or not client_id:
            return

        disconnected_at = str(connection.get('disconnected_at') or self._now_iso()).strip()
        reason = str(termination_reason or '').strip() or 'unexpected_disconnect'
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

            # The first completed close event owns its state, cause and details.
            if str(row['disconnected_at'] or '').strip():
                return

            snapshot = self._build_snapshot(connection, json_loads_dict(row['snapshot']))
            duration_ms = self._elapsed_ms(row['connected_at'], disconnected_at)
            last_seen_at = str(connection.get('last_seen_at') or row['last_seen_at'] or '').strip()
            normal_end = reason in (
                'server_requested_disconnect', 'client_exit', 'client_restart', 'client_update', 'client_paused'
            )
            termination_detail = {}
            if isinstance(details, dict):
                fields = (('command', 200),) if normal_end else (('summary', 500), ('traceback', 12000))
                for key, limit in fields:
                    value = str(details.get(key) or '').strip()
                    if value:
                        termination_detail[key] = value[:limit]
            conn.execute(
                '''
                UPDATE connection_sessions SET
                    disconnected_at = ?, disconnected_at_ms = ?, last_seen_at = ?, duration_ms = ?,
                    termination_reason = ?, termination_detail = ?, snapshot = ?
                WHERE machine_id = ? AND client_id = ?
                ''',
                (
                    disconnected_at, self._to_ms(disconnected_at), last_seen_at, duration_ms,
                    reason, compact_json_dumps(termination_detail),
                    compact_json_dumps(snapshot or {}), machine_id, client_id,
                ),
            )

    def get_history(
        self, machine_id: str, *, limit: int = 20, offset: int = 0,
        client_id_search: str = '', integrity: str = '', launch_mode: str = '',
        termination_reason: str = '',
    ) -> dict:
        machine_id_text = str(machine_id or '').strip()
        page_size = min(max(int(limit), 1), 20)
        page_offset = max(int(offset), 0)
        if not machine_id_text:
            return {
                'machine_id': '',
                'connection_count': 0, 'online_connection_count': 0,
                'total_online_duration_ms': 0,
                'sessions': [], 'has_more': False,
                'filter_options': {'integrity': [], 'launch_mode': [], 'termination_reason': []},
            }

        with self._lock:
            conn = self.database.connection()
            # One aggregate row retains the existing toolbar statistics. Only the
            # requested page of session snapshots is fetched or deserialized.
            totals = conn.execute('''
                SELECT COUNT(*) AS connection_count,
                       SUM(CASE WHEN disconnected_at = '' THEN 1 ELSE 0 END) AS online_count,
                       SUM(duration_ms) AS total_duration_ms
                FROM connection_sessions WHERE machine_id = ?
            ''', (machine_id_text,)).fetchone()
            # Filter and search before LIMIT/OFFSET so has_more describes visible results.
            # Missing snapshot values use the same `unknown` option as the UI.
            fields = {
                'integrity': "CASE WHEN json_valid(snapshot) THEN json_extract(snapshot, '$.integrity') END",
                'launch_mode': "CASE WHEN json_valid(snapshot) THEN json_extract(snapshot, '$.launch_mode') END",
                'termination_reason': 'termination_reason',
            }
            def value_expression(field):
                return f"COALESCE(NULLIF(LOWER(TRIM(CAST({fields[field]} AS TEXT))), ''), 'unknown')"

            # The dropdown values cover the entire machine, not only the loaded page.
            option_rows = conn.execute(
                'SELECT DISTINCT ' + ', '.join(
                    f'{value_expression(field)} AS {field}' for field in fields
                ) + ' FROM connection_sessions WHERE machine_id = ?',
                (machine_id_text,),
            ).fetchall()
            filter_options = {
                field: sorted({row[field] for row in option_rows}) for field in fields
            }

            search = str(client_id_search or '').strip()
            escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            query = 'SELECT * FROM connection_sessions WHERE machine_id = ?'
            params = [machine_id_text]
            if escaped:
                query += " AND client_id LIKE ? ESCAPE '\\'"
                params.append(f'%{escaped}%')
            selected = {
                'integrity': integrity,
                'launch_mode': launch_mode,
                'termination_reason': termination_reason,
            }
            for field, raw_value in selected.items():
                value = str(raw_value or '').strip().lower()
                if value:
                    query += f' AND {value_expression(field)} = ?'
                    params.append(value)
            query += ' ORDER BY connected_at_ms DESC, client_id DESC LIMIT ? OFFSET ?'
            rows = conn.execute(query, (*params, page_size + 1, page_offset)).fetchall()
            has_more = len(rows) > page_size
            now_iso = self._now_iso()
            return {
                'machine_id': machine_id_text,
                'connection_count': int(totals['connection_count'] or 0),
                'online_connection_count': int(totals['online_count'] or 0),
                'total_online_duration_ms': int(totals['total_duration_ms'] or 0),
                'sessions': [self._row_to_session(row, now_iso=now_iso) for row in rows[:page_size]],
                'has_more': has_more,
                'filter_options': filter_options,
            }
