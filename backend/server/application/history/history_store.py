"""Activity Center storage; Quick History uses its own writer and lifecycle."""
import threading
import time
from datetime import datetime, timezone

from core.utils.json_utils import compact_json_dumps, json_loads_typed
from server.application.history.history_view_service import HistoryViewService
from server.application.history.history_write_service import HistoryWriteService
from server.application.history.pinned_command_store import PinnedCommandStore
from server.application.history.quick_history import QuickHistoryStore


class CommandHistoryStore:
    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()
        self.artifact_service = None
        self.pinned_store = PinnedCommandStore(database, self._now_iso)
        self.quick_store = QuickHistoryStore(self)
        self.write_service = HistoryWriteService(self)
        self.view_service = HistoryViewService(self)
        with self._lock, self.database.transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS activity_records (
                activity_id TEXT PRIMARY KEY,
                machine_id TEXT NOT NULL,
                client_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                action TEXT NOT NULL,
                origin TEXT NOT NULL,
                presentation TEXT NOT NULL,
                status TEXT NOT NULL,
                invocation_json TEXT NOT NULL,
                resolved_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                started_at_ms INTEGER NOT NULL,
                finished_at TEXT,
                references_json TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                result_message_bytes INTEGER NOT NULL DEFAULT 0,
                result_data_bytes INTEGER NOT NULL DEFAULT 0,
                result_omitted INTEGER NOT NULL DEFAULT 0,
                result_summary TEXT NOT NULL DEFAULT ''
            )''')
            columns = {row[1] for row in conn.execute('PRAGMA table_info(activity_records)')}
            if not {'result_message_bytes', 'result_data_bytes', 'result_omitted', 'result_summary'} <= columns:
                raise RuntimeError('rch.db requires the one-time Client Result migration before starting Server')
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_activity_machine_time
                ON activity_records(machine_id, started_at_ms DESC, activity_id DESC)''')
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_activity_machine_status
                ON activity_records(machine_id, status, started_at_ms DESC)''')
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_activity_machine_kind
                ON activity_records(machine_id, kind, started_at_ms DESC)''')
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_activity_client_time
                ON activity_records(machine_id, client_id, started_at_ms DESC)''')
        self.write_service.interrupt_orphaned_activities()

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).astimezone().isoformat()

    @staticmethod
    def _now_ms():
        return int(time.time() * 1000)

    @staticmethod
    def _get_machine_id_from_conn(conn):
        info = getattr(conn, 'session_info', None)
        return getattr(info, 'machine_id', '') or 'unknown_machine'

    @staticmethod
    def _row_to_entry(row):
        if row is None:
            return None
        stored_result = json_loads_typed(row['result_json'], {})
        return {
            'activity_id': row['activity_id'], 'machine_id': row['machine_id'],
            'client_id': row['client_id'], 'kind': row['kind'],
            'action': row['action'], 'origin': row['origin'],
            'presentation': row['presentation'], 'status': row['status'],
            'invocation': json_loads_typed(row['invocation_json'], {}),
            'resolved': json_loads_typed(row['resolved_json'], {}),
            'result': stored_result.get('result', []),
            'recorded_at': stored_result.get('recorded_at', []),
            'result_omitted': bool(row['result_omitted']),
            'result_summary': row['result_summary'],
            'created_at': row['created_at'], 'started_at': row['started_at'],
            'finished_at': row['finished_at'],
            'references': json_loads_typed(row['references_json'], []),
            'summary': row['summary'],
        }

    def _get_entry(self, machine_id, activity_id):
        row = self.database.connection().execute(
            'SELECT * FROM activity_records WHERE machine_id = ? AND activity_id = ?',
            (machine_id, activity_id),
        ).fetchone()
        return self._row_to_entry(row)

    def _insert_entry(self, entry):
        started_ms = self._now_ms()
        self.database.connection().execute('''
            INSERT INTO activity_records (
                activity_id, machine_id, client_id, kind, action, origin, presentation,
                status, invocation_json, resolved_json, result_json,
                created_at, started_at, started_at_ms, finished_at, references_json, summary
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            entry['activity_id'], entry['machine_id'], entry['client_id'],
            entry['kind'], entry['action'], entry['origin'], entry['presentation'],
            entry['status'], compact_json_dumps(entry['invocation']),
            compact_json_dumps(entry['resolved']), compact_json_dumps({'result': [], 'recorded_at': []}),
            entry['created_at'], entry['started_at'], started_ms, entry['finished_at'],
            compact_json_dumps(entry['references']), entry['summary'],
        ))

    def _update_entry(self, entry):
        self.database.connection().execute('''
            UPDATE activity_records SET status = ?, references_json = ?,
            finished_at = ? WHERE machine_id = ? AND activity_id = ?
        ''', (
            entry['status'],
            compact_json_dumps(entry['references']), entry['finished_at'], entry['machine_id'], entry['activity_id'],
        ))

    def _list_execution_rows(self, machine_id, *, limit=None, cursor=None, query='', client_id='', kind='', errors=False):
        clauses, params = self._activity_filters(machine_id, query=query, client_id=client_id, kind=kind, errors=errors)
        if cursor is not None:
            cursor_ms, cursor_id = cursor
            clauses.append('(started_at_ms < ? OR (started_at_ms = ? AND activity_id < ?))')
            params.extend([cursor_ms, cursor_ms, cursor_id])
        sql = f"""
            SELECT activity_id, machine_id, client_id, kind, action, origin, presentation, status,
                   created_at, started_at, started_at_ms, finished_at, summary, result_summary,
                   result_omitted, (SELECT COUNT(*) FROM json_each(references_json)
                                    WHERE json_extract(value, '$.type') = 'artifact') AS file_count
            FROM activity_records WHERE {' AND '.join(clauses)}
            ORDER BY started_at_ms DESC, activity_id DESC
        """
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(int(limit))
        return self.database.connection().execute(sql, tuple(params)).fetchall()

    def _activity_filters(self, machine_id, *, query='', client_id='', kind='', errors=False):
        clauses = ['machine_id = ?']
        params = [machine_id]
        if client_id:
            clauses.append('client_id = ?')
            params.append(client_id)
        if kind:
            clauses.append('kind = ?')
            params.append(kind)
        if errors:
            clauses.append("status IN ('error','cancelled','interrupted','timed_out')")
        if query:
            clauses.append('''(instr(LOWER(action), LOWER(?)) > 0
                              OR instr(LOWER(summary), LOWER(?)) > 0
                              OR instr(LOWER(invocation_json), LOWER(?)) > 0
                              OR instr(LOWER(resolved_json), LOWER(?)) > 0)''')
            params.extend([query, query, query, query])
        return clauses, params

    def count_activities(self, machine_id, *, query='', client_id='', kind='', errors=False):
        clauses, params = self._activity_filters(machine_id, query=query, client_id=client_id, kind=kind, errors=errors)
        row = self.database.connection().execute(
            f"SELECT COUNT(*) FROM activity_records WHERE {' AND '.join(clauses)}", tuple(params)).fetchone()
        return int(row[0] if row else 0)

    def append_file_for_connection(self, conn, entry_id, artifact):
        return self.write_service.append_file_for_connection(conn, entry_id, artifact)

    def update_entry_status_for_connection(self, conn, entry_id, status, cwd_end=''):
        return self.write_service.update_entry_status_for_connection(conn, entry_id, status, cwd_end=cwd_end)

    def clear_history_for_connection(self, conn):
        return self.write_service.clear_history_for_connection(conn)

    def clear_history_by_machine_id(self, machine_id):
        return self.write_service.clear_history_by_machine_id(machine_id)

    def set_command_pinned_for_connection(self, conn, command, is_pinned):
        return self.write_service.set_command_pinned_for_connection(conn, command, is_pinned)

    def set_command_pinned_by_machine_id(self, machine_id, command, is_pinned):
        return self.write_service.set_command_pinned_by_machine_id(machine_id, command, is_pinned)

    def move_pinned_command_by_machine_id(self, machine_id, command, direction):
        return self.write_service.move_pinned_command_by_machine_id(machine_id, command, direction)

    def delete_execution_entry_by_machine_id(self, machine_id, entry_id):
        return self.write_service.delete_execution_entry_by_machine_id(machine_id, entry_id)

    def get_history_for_connection(self, conn):
        return self.view_service.get_history_for_connection(conn)

    def get_history_by_machine_id(self, machine_id):
        return self.view_service.get_history_by_machine_id(machine_id)
