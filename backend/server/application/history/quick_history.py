"""Quick History: terminal submissions and replay-index policy, independent of Activity.

Recording rules live here (not scattered through execution, Activity, or UI):
* Record manually submitted Web Terminal / Server CLI commands, regardless of
  success, error, cancellation, interruption or timeout.
* Never record `history`, `history clear`, `history run N` or `!N`:
  these are Quick management/replay operations, not new submitted commands.
* Never record Web API, Quick Action UI, Script Library UI or internal tasks
  (uploads, remote files, process, jobs, external tools).
* Never record the UI-only encoded `run_script __json__:` transport.
* A user's command is stored as typed, not as Alias expansion or replay target.
  Pins remain independent even after Recent is cleared or an Activity deleted.
"""
import re

from core.utils.json_utils import compact_json_dumps, json_loads_typed
from server.config.config import COMMAND_HISTORY_RECENT_LIMIT


QUICK_TERMINAL_SOURCES = frozenset({'web', 'web_terminal', 'cli'})
QUICK_EXCLUDED_TASK_TYPES = frozenset({'upload', 'remote_file', 'process', 'job_control', 'external_tool'})
QUICK_EXCLUDED_META_FLAGS = frozenset({'quick_action', 'script_run'})
QUICK_MANAGEMENT_PATTERN = re.compile(r'^history(?:\s|$)', re.IGNORECASE)
QUICK_REPLAY_PATTERN = re.compile(r'^(?:history\s+run\s+\d+|!\d+)$', re.IGNORECASE)
QUICK_TRANSPORT_PATTERN = re.compile(r'^run_script\s+__json__:', re.IGNORECASE)
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
        if any((metadata or {}).get(flag) for flag in QUICK_EXCLUDED_META_FLAGS):
            return False
        return not (cls.is_history_management_command(command)
                    or cls.is_history_replay_command(command)
                    or QUICK_TRANSPORT_PATTERN.match(command))


class QuickHistoryStore:
    """Owns Quick Recent writes and short-lived execution tracking, not Activity IDs."""

    def __init__(self, store):
        self.store = store
        self._pending = {}

    def begin(self, submission_id, conn, command):
        with self.store._lock:
            self._pending[submission_id] = (
                self.store._get_machine_id_from_conn(conn), str(command).strip())

    def discard(self, submission_id):
        with self.store._lock:
            self._pending.pop(submission_id, None)

    def finish(self, submission_id, status):
        with self.store._lock:
            submitted = self._pending.pop(submission_id, None)
            if submitted is None or status not in QUICK_FINAL_STATUSES:
                return
            machine_id, command = submitted
            when = self.store._now_iso()
            timestamp_ms = self.store._now_ms()
            snapshot = {'command': command, 'raw_command': command, 'status': status,
                        'created_at': when, 'finished_at': when, 'files': []}
            with self.store.database.transaction():
                conn = self.store.database.connection()
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

    def clear(self, machine_id):
        with self.store._lock, self.store.database.transaction():
            self.store.database.connection().execute(
                'DELETE FROM command_recents WHERE machine_id = ?', (machine_id,))
            # Do not clear the user's independent pinned_commands collection.

    def list_recents(self, machine_id):
        rows = self.store.database.connection().execute('''
            SELECT command, last_used_at, use_count, snapshot_json FROM command_recents
            WHERE machine_id = ? ORDER BY last_used_at_ms DESC, command DESC LIMIT ?
        ''', (machine_id, COMMAND_HISTORY_RECENT_LIMIT)).fetchall()
        result = []
        for row in rows:
            snapshot = json_loads_typed(row['snapshot_json'], {})
            snapshot.update({'command': row['command'], 'last_used_at': row['last_used_at'],
                             'use_count': int(row['use_count'] or 0)})
            result.append(snapshot)
        return result
