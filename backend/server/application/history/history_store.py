import threading
import time
import uuid
from datetime import datetime

from core.utils.json_utils import compact_json_dumps, json_loads_typed
from server.application.history.history_view_service import HistoryViewService
from server.application.history.history_write_service import HistoryWriteService
from server.application.history.pinned_command_store import PinnedCommandStore
from server.config.config import (
    COMMAND_HISTORY_MAX_OUTPUT_RECORD_CHARS,
    COMMAND_HISTORY_MAX_OUTPUT_RECORDS,
    COMMAND_HISTORY_MAX_OUTPUT_SUMMARY_CHARS,
    COMMAND_HISTORY_RECENT_LIMIT,
)


class CommandHistoryStore:
    """SQLite-backed command execution / recent / pinned history store."""

    MAX_OUTPUT_RECORD_CHARS = COMMAND_HISTORY_MAX_OUTPUT_RECORD_CHARS
    MAX_OUTPUT_SUMMARY_CHARS = COMMAND_HISTORY_MAX_OUTPUT_SUMMARY_CHARS
    MAX_OUTPUT_RECORDS = COMMAND_HISTORY_MAX_OUTPUT_RECORDS
    RECENT_LIMIT = COMMAND_HISTORY_RECENT_LIMIT
    TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()
        self.artifact_service = None
        self.pinned_store = PinnedCommandStore(database, self._now_text)
        self.write_service = HistoryWriteService(self)
        self.view_service = HistoryViewService(self)

    def _now_text(self) -> str:
        return datetime.now().strftime(self.TIME_FORMAT)

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _parse_time_text(self, value: str):
        text = str(value or '').strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, self.TIME_FORMAT)
        except Exception:
            return None

    def _build_entry(self, conn, command: str, source: str) -> dict:
        session_info = getattr(conn, 'session_info', None)
        started_text = self._now_text()
        return {
            'entry_id': uuid.uuid4().hex,
            'time': started_text,
            'started_at': started_text,
            'finished_at': '',
            'duration_ms': 0,
            'command': command,
            'raw_command': command,
            'source': source,
            'status': 'running',
            'final_status': '',
            'hostname': getattr(session_info, 'hostname', '') or 'unknown_host',
            'machine_id': getattr(session_info, 'machine_id', '') or 'unknown_machine',
            'client_id': getattr(session_info, 'client_id', '') or '',
            'addr': getattr(session_info, 'addr', '') or '',
            'cwd_start': getattr(session_info, 'cwd', '') or '',
            'cwd_end': '',
            'has_output': False,
            'output_summary': '',
            'output_line_count': 0,
            'output_chunk_count': 0,
            'output_char_count': 0,
            'output_stored_char_count': 0,
            'output_truncated': False,
            'output_record_seq': 0,
            'output_records': [],
            'has_files': False,
            'file_count': 0,
            'files': [],
        }

    def _get_machine_id_from_conn(self, conn) -> str:
        session_info = getattr(conn, 'session_info', None)
        return getattr(session_info, 'machine_id', '') or 'unknown_machine'

    @staticmethod
    def _safe_text(text) -> str:
        if text is None:
            return ''
        return str(text)

    @staticmethod
    def _count_output_lines(text: str) -> int:
        if not text:
            return 0
        return max(len(text.splitlines()), 1)

    def _build_output_summary(self, entry: dict) -> str:
        if entry.get('has_files'):
            file_count = int(entry.get('file_count', 0) or 0)
            if file_count > 0:
                return f'Produced {file_count} file(s)'

        for item in reversed(entry.get('output_records') or []):
            text = self._safe_text(item.get('text')).strip()
            if not text:
                continue
            if '\n' not in text and '\r' not in text:
                return text[:self.MAX_OUTPUT_SUMMARY_CHARS]
            break

        status = entry.get('status') or ''
        if status == 'success':
            return 'Command completed'
        if status == 'error':
            return 'Command failed'
        return 'No output'

    def _update_duration(self, entry: dict):
        start_dt = self._parse_time_text(entry.get('started_at') or '')
        end_dt = self._parse_time_text(entry.get('finished_at') or '')
        if start_dt is None or end_dt is None:
            entry['duration_ms'] = 0
            return
        entry['duration_ms'] = max(int((end_dt - start_dt).total_seconds() * 1000), 0)

    def _row_to_entry(self, row) -> dict | None:
        if row is None:
            return None
        return {
            '_started_at_ms': int(row['started_at_ms'] or 0),
            'entry_id': row['entry_id'],
            'time': row['time_text'],
            'started_at': row['started_at'],
            'finished_at': row['finished_at'],
            'duration_ms': int(row['duration_ms'] or 0),
            'command': row['command'],
            'raw_command': row['raw_command'],
            'source': row['source'],
            'status': row['status'],
            'final_status': row['final_status'],
            'hostname': row['hostname'],
            'machine_id': row['machine_id'],
            'client_id': row['client_id'],
            'addr': row['addr'],
            'cwd_start': row['cwd_start'],
            'cwd_end': row['cwd_end'],
            'has_output': bool(row['has_output']),
            'output_summary': row['output_summary'],
            'output_line_count': int(row['output_line_count'] or 0),
            'output_chunk_count': int(row['output_chunk_count'] or 0),
            'output_char_count': int(row['output_char_count'] or 0),
            'output_stored_char_count': int(row['output_stored_char_count'] or 0),
            'output_truncated': bool(row['output_truncated']),
            'output_record_seq': int(row['output_record_seq'] or 0),
            'output_records': json_loads_typed(row['output_records_json'], []),
            'has_files': bool(row['has_files']),
            'file_count': int(row['file_count'] or 0),
            'files': json_loads_typed(row['files_json'], []),
        }

    def _insert_entry(self, entry: dict):
        started_at_ms = self._now_ms()
        self.database.connection().execute(
            '''
            INSERT INTO command_executions (
                entry_id, machine_id, client_id, hostname, addr, command, raw_command,
                source, status, final_status, time_text, started_at, started_at_ms,
                finished_at, finished_at_ms, duration_ms, cwd_start, cwd_end,
                has_output, output_summary, output_line_count, output_chunk_count,
                output_char_count, output_stored_char_count, output_truncated,
                output_record_seq, output_records_json, has_files, file_count, files_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                entry['entry_id'], entry['machine_id'], entry['client_id'], entry['hostname'], entry['addr'],
                entry['command'], entry['raw_command'], entry['source'], entry['status'], entry['final_status'],
                entry['time'], entry['started_at'], started_at_ms, int(entry.get('duration_ms', 0) or 0),
                entry['cwd_start'], entry['cwd_end'], int(bool(entry.get('has_output'))), entry['output_summary'],
                int(entry.get('output_line_count', 0) or 0), int(entry.get('output_chunk_count', 0) or 0),
                int(entry.get('output_char_count', 0) or 0), int(entry.get('output_stored_char_count', 0) or 0),
                int(bool(entry.get('output_truncated'))), int(entry.get('output_record_seq', 0) or 0),
                compact_json_dumps(entry.get('output_records') or []), int(bool(entry.get('has_files'))),
                int(entry.get('file_count', 0) or 0), compact_json_dumps(entry.get('files') or []),
            ),
        )
        entry['_started_at_ms'] = started_at_ms
        return started_at_ms

    def _get_entry(self, machine_id: str, entry_id: str) -> dict | None:
        row = self.database.connection().execute(
            'SELECT * FROM command_executions WHERE machine_id = ? AND entry_id = ?',
            (machine_id, entry_id),
        ).fetchone()
        return self._row_to_entry(row)

    def _update_entry(self, entry: dict):
        finished_at = str(entry.get('finished_at') or '')
        finished_dt = self._parse_time_text(finished_at) if finished_at else None
        finished_at_ms = int(finished_dt.timestamp() * 1000) if finished_dt is not None else 0
        self.database.connection().execute(
            '''
            UPDATE command_executions SET
                client_id = ?, hostname = ?, addr = ?, command = ?, raw_command = ?, source = ?,
                status = ?, final_status = ?, time_text = ?, started_at = ?, finished_at = ?,
                finished_at_ms = ?, duration_ms = ?, cwd_start = ?, cwd_end = ?, has_output = ?,
                output_summary = ?, output_line_count = ?, output_chunk_count = ?, output_char_count = ?,
                output_stored_char_count = ?, output_truncated = ?, output_record_seq = ?,
                output_records_json = ?, has_files = ?, file_count = ?, files_json = ?
            WHERE machine_id = ? AND entry_id = ?
            ''',
            (
                entry.get('client_id', ''), entry.get('hostname', ''), entry.get('addr', ''),
                entry.get('command', ''), entry.get('raw_command', ''), entry.get('source', ''),
                entry.get('status', ''), entry.get('final_status', ''), entry.get('time', ''),
                entry.get('started_at', ''), finished_at, finished_at_ms, int(entry.get('duration_ms', 0) or 0),
                entry.get('cwd_start', ''), entry.get('cwd_end', ''), int(bool(entry.get('has_output'))),
                entry.get('output_summary', ''), int(entry.get('output_line_count', 0) or 0),
                int(entry.get('output_chunk_count', 0) or 0), int(entry.get('output_char_count', 0) or 0),
                int(entry.get('output_stored_char_count', 0) or 0), int(bool(entry.get('output_truncated'))),
                int(entry.get('output_record_seq', 0) or 0), compact_json_dumps(entry.get('output_records') or []),
                int(bool(entry.get('has_files'))), int(entry.get('file_count', 0) or 0),
                compact_json_dumps(entry.get('files') or []), entry.get('machine_id', ''), entry.get('entry_id', ''),
            ),
        )

    def _get_latest_entry_for_command(self, machine_id: str, command: str) -> dict | None:
        row = self.database.connection().execute(
            '''
            SELECT * FROM command_executions
            WHERE machine_id = ? AND command = ?
            ORDER BY started_at_ms DESC, entry_id DESC
            LIMIT 1
            ''',
            (machine_id, command),
        ).fetchone()
        return self._row_to_entry(row)

    def _upsert_recent(self, entry: dict, *, increment_use: bool):
        started_at_ms = int(entry.get('_started_at_ms', 0) or 0)
        if started_at_ms <= 0:
            row = self.database.connection().execute(
                'SELECT started_at_ms FROM command_executions WHERE entry_id = ?',
                (entry.get('entry_id', ''),),
            ).fetchone()
            started_at_ms = int(row['started_at_ms'] or 0) if row else self._now_ms()

        snapshot = dict(entry)
        snapshot.pop('output_records', None)
        snapshot.pop('_started_at_ms', None)
        conn = self.database.connection()
        existing = conn.execute(
            'SELECT use_count FROM command_recents WHERE machine_id = ? AND command = ?',
            (entry.get('machine_id', ''), entry.get('command', '')),
        ).fetchone()
        use_count = 1 if existing is None else int(existing['use_count'] or 0) + (1 if increment_use else 0)

        conn.execute(
            '''
            INSERT INTO command_recents(
                machine_id, command, last_entry_id, last_used_at, last_used_at_ms, use_count, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(machine_id, command) DO UPDATE SET
                last_entry_id = excluded.last_entry_id,
                last_used_at = excluded.last_used_at,
                last_used_at_ms = excluded.last_used_at_ms,
                use_count = excluded.use_count,
                snapshot_json = excluded.snapshot_json
            ''',
            (
                entry.get('machine_id', ''), entry.get('command', ''), entry.get('entry_id', ''),
                entry.get('time') or entry.get('started_at') or self._now_text(), started_at_ms,
                use_count, compact_json_dumps(snapshot),
            ),
        )
        self._trim_recents(entry.get('machine_id', ''))

    def _trim_recents(self, machine_id: str):
        self.database.connection().execute(
            '''
            DELETE FROM command_recents
            WHERE rowid IN (
                SELECT rowid FROM command_recents
                WHERE machine_id = ?
                ORDER BY last_used_at_ms DESC, command DESC
                LIMIT -1 OFFSET ?
            )
            ''',
            (str(machine_id or '').strip() or 'unknown_machine', self.RECENT_LIMIT),
        )

    def _update_recent_snapshot_if_present(self, entry: dict):
        snapshot = dict(entry)
        snapshot.pop('output_records', None)
        snapshot.pop('_started_at_ms', None)
        self.database.connection().execute(
            '''UPDATE command_recents
               SET last_entry_id = ?, last_used_at = ?, snapshot_json = ?
               WHERE machine_id = ? AND command = ? AND last_entry_id = ?''',
            (
                entry.get('entry_id', ''), entry.get('time') or entry.get('started_at') or '',
                compact_json_dumps(snapshot), entry.get('machine_id', ''), entry.get('command', ''),
                entry.get('entry_id', ''),
            ),
        )

    def _rebuild_recent_for_command(self, machine_id: str, command: str):
        conn = self.database.connection()
        row = conn.execute(
            '''SELECT * FROM command_executions WHERE machine_id = ? AND command = ?
               ORDER BY started_at_ms DESC, entry_id DESC LIMIT 1''',
            (machine_id, command),
        ).fetchone()
        if row is None:
            conn.execute(
                'DELETE FROM command_recents WHERE machine_id = ? AND command = ?',
                (machine_id, command),
            )
            return

        entry = self._row_to_entry(row)
        count_row = conn.execute(
            'SELECT COUNT(*) FROM command_executions WHERE machine_id = ? AND command = ?',
            (machine_id, command),
        ).fetchone()
        snapshot = dict(entry)
        snapshot.pop('output_records', None)
        snapshot.pop('_started_at_ms', None)
        conn.execute(
            '''
            INSERT INTO command_recents(
                machine_id, command, last_entry_id, last_used_at, last_used_at_ms, use_count, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(machine_id, command) DO UPDATE SET
                last_entry_id = excluded.last_entry_id,
                last_used_at = excluded.last_used_at,
                last_used_at_ms = excluded.last_used_at_ms,
                use_count = excluded.use_count,
                snapshot_json = excluded.snapshot_json
            ''',
            (
                machine_id, command, entry['entry_id'], entry.get('time') or entry.get('started_at') or '',
                int(row['started_at_ms'] or 0), int(count_row[0] if count_row else 1), compact_json_dumps(snapshot),
            ),
        )
        self._trim_recents(machine_id)

    def _list_recents(self, machine_id: str) -> list[dict]:
        rows = self.database.connection().execute(
            '''
            SELECT command, last_entry_id, last_used_at, use_count, snapshot_json
            FROM command_recents
            WHERE machine_id = ?
            ORDER BY last_used_at_ms DESC, command DESC
            LIMIT ?
            ''',
            (machine_id, self.RECENT_LIMIT),
        ).fetchall()
        result = []
        for row in rows:
            snapshot = json_loads_typed(row['snapshot_json'], {})
            snapshot['command'] = row['command']
            snapshot['last_entry_id'] = row['last_entry_id']
            snapshot['time'] = snapshot.get('time') or row['last_used_at']
            snapshot['use_count'] = int(row['use_count'] or 0)
            result.append(snapshot)
        return result

    def _delete_execution(self, machine_id: str, entry_id: str) -> bool:
        conn = self.database.connection()
        row = conn.execute(
            'SELECT command FROM command_executions WHERE machine_id = ? AND entry_id = ?',
            (machine_id, entry_id),
        ).fetchone()
        if row is None:
            return False
        command = row['command']
        conn.execute(
            'DELETE FROM command_executions WHERE machine_id = ? AND entry_id = ?',
            (machine_id, entry_id),
        )
        self._rebuild_recent_for_command(machine_id, command)
        return True

    def _clear_execution_history(self, machine_id: str):
        with self.database.transaction() as conn:
            conn.execute('DELETE FROM command_executions WHERE machine_id = ?', (machine_id,))
            conn.execute('DELETE FROM command_recents WHERE machine_id = ?', (machine_id,))

    def _list_execution_rows(
        self,
        machine_id: str,
        *,
        limit: int | None = None,
        cursor: tuple[int, str] | None = None,
        query: str = '',
        client_id: str = '',
    ):
        params = [machine_id]
        where = 'machine_id = ?'
        client_id_text = str(client_id or '').strip()
        if client_id_text:
            where += ' AND client_id = ?'
            params.append(client_id_text)
        query_text = str(query or '').strip()
        if query_text:
            where += ' AND instr(LOWER(command), LOWER(?)) > 0'
            params.append(query_text)
        if cursor is not None:
            cursor_ms, cursor_entry_id = cursor
            where += ' AND (started_at_ms < ? OR (started_at_ms = ? AND entry_id < ?))'
            params.extend([int(cursor_ms), int(cursor_ms), str(cursor_entry_id)])
        sql = f'SELECT * FROM command_executions WHERE {where} ORDER BY started_at_ms DESC, entry_id DESC'
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(int(limit))
        return self.database.connection().execute(sql, tuple(params)).fetchall()

    def create_entry_for_connection(self, conn, command: str, source: str = 'cli'):
        return self.write_service.create_entry_for_connection(conn, command, source=source)

    def append_output_for_connection(self, conn, entry_id: str, status: int, text: str, eof: int = 0):
        return self.write_service.append_output_for_connection(conn, entry_id, status, text, eof=eof)

    def append_file_for_connection(self, conn, entry_id: str, artifact: dict):
        return self.write_service.append_file_for_connection(conn, entry_id, artifact)

    def update_entry_command_for_connection(self, conn, entry_id: str, command: str):
        return self.write_service.update_entry_command_for_connection(conn, entry_id, command)

    def update_entry_status_for_connection(self, conn, entry_id: str, status: str, cwd_end: str = ''):
        return self.write_service.update_entry_status_for_connection(conn, entry_id, status, cwd_end=cwd_end)

    def clear_history_for_connection(self, conn):
        return self.write_service.clear_history_for_connection(conn)

    def clear_history_by_machine_id(self, machine_id: str):
        return self.write_service.clear_history_by_machine_id(machine_id)

    def set_command_pinned_for_connection(self, conn, command: str, is_pinned: bool):
        return self.write_service.set_command_pinned_for_connection(conn, command, is_pinned)

    def set_command_pinned_by_machine_id(self, machine_id: str, command: str, is_pinned: bool):
        return self.write_service.set_command_pinned_by_machine_id(machine_id, command, is_pinned)

    def move_pinned_command_by_machine_id(self, machine_id: str, command: str, direction: str):
        return self.write_service.move_pinned_command_by_machine_id(machine_id, command, direction)

    def delete_execution_entry_by_machine_id(self, machine_id: str, entry_id: str):
        return self.write_service.delete_execution_entry_by_machine_id(machine_id, entry_id)

    def get_history_for_connection(self, conn) -> list:
        return self.view_service.get_history_for_connection(conn)

    def get_history_by_machine_id(self, machine_id: str) -> list:
        return self.view_service.get_history_by_machine_id(machine_id)
