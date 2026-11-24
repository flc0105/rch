"""Activity Center storage; Quick History uses its own writer and lifecycle."""
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
        self.artifact_service = None
        self.pinned_store = PinnedCommandStore(database, self.now_iso)
        self.quick_store = QuickHistoryStore(database, self.machine_id_for_connection, self.now_iso, self.now_ms)
        self.write_service = HistoryWriteService(self)
        self.view_service = HistoryViewService(self)
        self.write_service.interrupt_orphaned_activities()

    @staticmethod
    def now_iso():
        return datetime.now(timezone.utc).astimezone().isoformat()

    @staticmethod
    def now_ms():
        return int(time.time() * 1000)

    @staticmethod
    def machine_id_for_connection(conn):
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

    def get_entry(self, machine_id, activity_id):
        row = self.database.fetch_one(
            'SELECT * FROM activity_records WHERE machine_id = ? AND activity_id = ?',
            (machine_id, activity_id),
        )
        return self._row_to_entry(row)

    def insert_entry(self, entry):
        started_ms = self.now_ms()
        self.database.execute('''
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

    def update_entry(self, entry):
        self.database.execute('''
            UPDATE activity_records SET status = ?, references_json = ?,
            finished_at = ? WHERE machine_id = ? AND activity_id = ?
        ''', (
            entry['status'],
            compact_json_dumps(entry['references']), entry['finished_at'], entry['machine_id'], entry['activity_id'],
        ))

    def list_execution_rows(self, machine_id, *, limit=None, cursor=None, query='', client_id='', kind='', errors=False):
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
        return [dict(row) for row in self.database.fetch_all(sql, tuple(params))]

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
        row = self.database.fetch_one(
            f"SELECT COUNT(*) FROM activity_records WHERE {' AND '.join(clauses)}", tuple(params))
        return int(row[0] if row else 0)

    def transaction(self):
        return self.database.transaction()

    def read_snapshot(self):
        return self.database.read_snapshot()

    def interrupt_active(self, finished_at):
        self.database.execute(
            "UPDATE activity_records SET status = 'interrupted', finished_at = ? "
            "WHERE status IN ('running', 'cancelling')", (finished_at,))

    def get_active_result_stats(self, machine_id, activity_id):
        row = self.database.fetch_one(
            "SELECT result_message_bytes, result_data_bytes, result_omitted, result_summary "
            "FROM activity_records WHERE machine_id = ? AND activity_id = ? "
            "AND status IN ('running', 'cancelling')", (machine_id, activity_id))
        return dict(row) if row is not None else None

    def append_result(self, machine_id, activity_id, result, recorded_at, *,
                      message_bytes, data_bytes, omitted, summary):
        self.database.execute(
            "UPDATE activity_records SET result_json = "
            "json_insert(result_json, '$.result[#]', json(?), '$.recorded_at[#]', ?), "
            "result_message_bytes = ?, result_data_bytes = ?, result_omitted = ?, result_summary = ? "
            "WHERE machine_id = ? AND activity_id = ?",
            (compact_json_dumps(result), recorded_at, message_bytes, data_bytes,
             int(omitted), summary, machine_id, activity_id))

    def delete_activities(self, machine_id, *, query='', kind='', errors=False):
        clauses, params = self._activity_filters(machine_id, query=query, kind=kind, errors=errors)
        with self.transaction():
            return self.database.execute(
                f"DELETE FROM activity_records WHERE {' AND '.join(clauses)}", tuple(params)).rowcount

    def delete_activity(self, machine_id, activity_id):
        with self.transaction():
            return self.database.execute(
                'DELETE FROM activity_records WHERE machine_id = ? AND activity_id = ?',
                (machine_id, activity_id)).rowcount > 0

    def count_by_client_ids(self, machine_id, client_ids):
        if not client_ids:
            return {}
        placeholders = ', '.join('?' for _ in client_ids)
        rows = self.database.fetch_all(
            f"SELECT client_id, COUNT(*) AS command_count FROM activity_records "
            f"WHERE machine_id = ? AND client_id IN ({placeholders}) GROUP BY client_id",
            (machine_id, *client_ids))
        return {row['client_id']: int(row['command_count']) for row in rows}

    def connection_totals(self, machine_id):
        row = self.database.fetch_one(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN client_id = '' THEN 1 ELSE 0 END) AS unassigned "
            "FROM activity_records WHERE machine_id = ?", (machine_id,))
        return {'total': int(row['total'] or 0), 'unassigned': int(row['unassigned'] or 0)}

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
