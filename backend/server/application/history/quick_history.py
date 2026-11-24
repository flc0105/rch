"""Quick History: terminal submissions and replay-index policy, independent of Activity.

Recording rules live here (not scattered through execution, Activity, or UI):
* Record manually submitted Web Terminal / Server CLI / RCH CLI commands, regardless of
  success, error, cancellation, interruption or timeout.
* Never record `history`, `history clear`, `history run N` or `!N`:
  these are Quick management/replay operations, not new submitted commands.
* Never record Web API, Quick Action UI, Script Library UI or internal tasks
  (uploads, remote files, process, jobs, external tools).
* A user's command is stored as typed, not as Alias expansion or replay target.
  Pins remain independent even after Recent is cleared or an Activity deleted.
"""
import re
import threading

from core.utils.json_utils import compact_json_dumps, json_loads_typed
from server.application.history.history_record_policy import CommandHistoryRecordPolicy
from server.config.config import COMMAND_HISTORY_RECENT_LIMIT


QUICK_TERMINAL_SOURCES = frozenset({'web', 'web_terminal', 'cli', 'rch_cli'})
QUICK_EXCLUDED_TASK_TYPES = frozenset({'upload', 'remote_file', 'process', 'job_control', 'external_tool'})
QUICK_EXCLUDED_META_FLAGS = frozenset({'quick_action', 'script_run'})
QUICK_MANAGEMENT_PATTERN = re.compile(r'^history(?:\s|$)', re.IGNORECASE)
QUICK_REPLAY_PATTERN = re.compile(r'^(?:history\s+run\s+\d+|!\d+)$', re.IGNORECASE)
QUICK_FINAL_STATUSES = frozenset({'success', 'error', 'cancelled', 'interrupted', 'timed_out', 'stopped'})


class QuickHistoryRecordPolicy:
    @staticmethod
    def is_history_replay_command(command):
        return bool(QUICK_REPLAY_PATTERN.fullmatch(str(command or '').strip()))

    @staticmethod
    def is_history_management_command(command):
        return bool(QUICK_MANAGEMENT_PATTERN.match(str(command or '').strip()))

    @classmethod
    def should_record(cls, command, *, source='', task_type='', metadata=None):
        command = str(command or '').strip()
        if not command or source not in QUICK_TERMINAL_SOURCES:
            return False
        if str(task_type or '').strip().lower() in QUICK_EXCLUDED_TASK_TYPES:
            return False
        if CommandHistoryRecordPolicy.is_internal_external_tool_command(command):
            return False
        if any((metadata or {}).get(flag) for flag in QUICK_EXCLUDED_META_FLAGS):
            return False
        return not (cls.is_history_management_command(command)
                    or cls.is_history_replay_command(command)
                    )


class QuickHistoryStore:
    """Owns Quick Recent writes and short-lived execution tracking, not Activity IDs."""

    def __init__(self, database, machine_id_for_connection, now_iso, now_ms):
        self.database = database
        self.machine_id_for_connection = machine_id_for_connection
        self.now_iso = now_iso
        self.now_ms = now_ms
        self._pending = {}
        self._pending_lock = threading.RLock()

    def begin(self, submission_id, conn, command):
        with self._pending_lock:
            self._pending[submission_id] = (
                self.machine_id_for_connection(conn), str(command).strip())

    def discard(self, submission_id):
        with self._pending_lock:
            self._pending.pop(submission_id, None)

    def finish(self, submission_id, status):
        with self._pending_lock:
            submitted = self._pending.pop(submission_id, None)
        if submitted is None or status not in QUICK_FINAL_STATUSES:
            return
        machine_id, command = submitted
        when = self.now_iso()
        timestamp_ms = self.now_ms()
        snapshot = {'command': command, 'raw_command': command, 'status': status,
                    'created_at': when, 'finished_at': when, 'files': []}
        with self.database.transaction() as conn:
            conn.execute('''
                INSERT INTO command_recents (
                    machine_id, command, last_used_at, last_used_at_ms,
                    use_count, snapshot_json
                ) VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(machine_id, command) DO UPDATE SET
                    last_used_at = excluded.last_used_at,
                    last_used_at_ms = excluded.last_used_at_ms,
                    use_count = command_recents.use_count + 1,
                    snapshot_json = excluded.snapshot_json
            ''', (machine_id, command, when, timestamp_ms, compact_json_dumps(snapshot)))
            conn.execute('''
                DELETE FROM command_recents WHERE rowid IN (
                    SELECT rowid FROM command_recents WHERE machine_id = ?
                    ORDER BY last_used_at_ms DESC, command DESC LIMIT -1 OFFSET ?
                )
            ''', (machine_id, COMMAND_HISTORY_RECENT_LIMIT))

    def clear(self, machine_id, *, query=''):
        query = str(query or '').strip()
        with self.database.transaction() as conn:
            if query:
                # Match the UI's case-insensitive substring search, including Unicode text.
                commands = [row[0] for row in conn.execute(
                    'SELECT command FROM command_recents WHERE machine_id = ?', (machine_id,))
                    if query.lower() in row[0].lower()]
                conn.executemany(
                    'DELETE FROM command_recents WHERE machine_id = ? AND command = ?',
                    ((machine_id, command) for command in commands))
            else:
                conn.execute(
                    'DELETE FROM command_recents WHERE machine_id = ?', (machine_id,))
            # Do not clear the user's independent pinned_commands collection.

    def get_recent(self, machine_id, command):
        row = self.database.fetch_one(
            'SELECT snapshot_json, last_used_at, use_count FROM command_recents WHERE machine_id = ? AND command = ?',
            (machine_id, command))
        if row is None:
            return None
        return {'snapshot': json_loads_typed(row['snapshot_json'], {}),
                'last_used_at': row['last_used_at'], 'use_count': int(row['use_count'])}

    def list_recents(self, machine_id):
        rows = self.database.fetch_all('''
            SELECT command, last_used_at, use_count, snapshot_json FROM command_recents
            WHERE machine_id = ? ORDER BY last_used_at_ms DESC, command DESC LIMIT ?
        ''', (machine_id, COMMAND_HISTORY_RECENT_LIMIT))
        result = []
        for row in rows:
            snapshot = json_loads_typed(row['snapshot_json'], {})
            snapshot.update({'command': row['command'], 'last_used_at': row['last_used_at'],
                             'use_count': int(row['use_count'] or 0)})
            result.append(snapshot)
        return result
