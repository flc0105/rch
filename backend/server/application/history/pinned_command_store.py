

from core.utils.json_utils import compact_json_dumps, json_loads_dict
class PinnedCommandStore:
    """SQLite-backed machine-level pinned command registry."""

    SNAPSHOT_FIELDS = (
        'entry_id', 'time', 'started_at', 'finished_at', 'duration_ms', 'command',
        'raw_command', 'source', 'status', 'final_status', 'hostname', 'machine_id',
        'client_id', 'addr', 'cwd_start', 'cwd_end', 'has_output', 'output_summary',
        'output_line_count', 'output_chunk_count', 'output_char_count',
        'output_stored_char_count', 'output_truncated', 'output_record_seq',
        'has_files', 'file_count', 'files',
    )

    def __init__(self, database, now_text_provider):
        self.database = database
        self.now_text_provider = now_text_provider

    def _now_text(self) -> str:
        return self.now_text_provider()

    @staticmethod
    def _normalize_int(value, default: int = 0) -> int:
        try:
            return int(value or default)
        except Exception:
            return default

    def _sanitize_snapshot(self, snapshot: dict | None, command: str = '') -> dict:
        source = snapshot if isinstance(snapshot, dict) else {}
        copied = {field: source.get(field) for field in self.SNAPSHOT_FIELDS if field in source}
        command_text = str(copied.get('command') or command or '').strip()
        copied['command'] = command_text
        copied['raw_command'] = str(copied.get('raw_command') or command_text).strip()
        copied['status'] = str(copied.get('status') or '').strip()
        copied['time'] = str(copied.get('time') or '').strip()
        copied['files'] = list(copied.get('files') or [])
        copied['file_count'] = self._normalize_int(copied.get('file_count'), len(copied['files']))
        copied['has_files'] = bool(copied.get('has_files') or copied['file_count'] > 0)
        copied.pop('output_records', None)
        return copied

    def get_items(self, machine_id: str) -> list:
        rows = self.database.connection().execute(
            '''
            SELECT command, pinned_at, pin_order, snapshot_json
            FROM pinned_commands
            WHERE machine_id = ?
            ORDER BY pin_order ASC, pinned_at ASC, command ASC
            ''',
            (str(machine_id or '').strip() or 'unknown_machine',),
        ).fetchall()
        return [
            {
                'command': row['command'],
                'pinned_at': row['pinned_at'],
                'pin_order': int(row['pin_order'] or 0),
                'snapshot': self._sanitize_snapshot(json_loads_dict(row['snapshot_json']), row['command']),
            }
            for row in rows
        ]

    def get_command_set(self, machine_id: str) -> set:
        return {item['command'] for item in self.get_items(machine_id)}

    def set_command_pinned(self, machine_id: str, command: str, is_pinned: bool, seed_entry: dict | None = None) -> bool:
        machine_id_text = str(machine_id or '').strip() or 'unknown_machine'
        command_text = str(command or '').strip()
        if not command_text:
            return False

        conn = self.database.connection()
        existing = conn.execute(
            'SELECT command, snapshot_json FROM pinned_commands WHERE machine_id = ? AND command = ?',
            (machine_id_text, command_text),
        ).fetchone()

        if not bool(is_pinned):
            if existing is None:
                return False
            conn.execute(
                'DELETE FROM pinned_commands WHERE machine_id = ? AND command = ?',
                (machine_id_text, command_text),
            )
            self._normalize_orders(machine_id_text)
            return True

        snapshot = self._sanitize_snapshot(seed_entry, command_text)
        if existing is None:
            row = conn.execute(
                'SELECT COALESCE(MAX(pin_order), 0) FROM pinned_commands WHERE machine_id = ?',
                (machine_id_text,),
            ).fetchone()
            next_order = int(row[0] if row else 0) + 1
            conn.execute(
                '''
                INSERT INTO pinned_commands(machine_id, command, pinned_at, pin_order, snapshot_json)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (machine_id_text, command_text, self._now_text(), next_order, compact_json_dumps(snapshot or {})),
            )
            return True

        current_snapshot = json_loads_dict(existing['snapshot_json'])
        if snapshot and snapshot != current_snapshot:
            conn.execute(
                'UPDATE pinned_commands SET snapshot_json = ? WHERE machine_id = ? AND command = ?',
                (compact_json_dumps(snapshot or {}), machine_id_text, command_text),
            )
            return True
        return False

    def _normalize_orders(self, machine_id: str):
        conn = self.database.connection()
        rows = conn.execute(
            '''SELECT command FROM pinned_commands WHERE machine_id = ?
               ORDER BY pin_order ASC, pinned_at ASC, command ASC''',
            (machine_id,),
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            conn.execute(
                'UPDATE pinned_commands SET pin_order = ? WHERE machine_id = ? AND command = ?',
                (index, machine_id, row['command']),
            )

    def move_pinned_command(self, machine_id: str, command: str, direction: str) -> bool:
        machine_id_text = str(machine_id or '').strip() or 'unknown_machine'
        command_text = str(command or '').strip()
        direction_text = str(direction or '').strip().lower()
        if not command_text:
            raise ValueError('command is required')
        if direction_text not in ('up', 'down'):
            raise ValueError('direction must be up or down')

        items = self.get_items(machine_id_text)
        current_index = next((i for i, item in enumerate(items) if item['command'] == command_text), -1)
        if current_index < 0:
            raise ValueError('Only pinned commands can be moved')

        target_index = current_index - 1 if direction_text == 'up' else current_index + 1
        if target_index < 0 or target_index >= len(items):
            return False

        items[current_index], items[target_index] = items[target_index], items[current_index]
        with self.database.transaction() as conn:
            for index, item in enumerate(items, start=1):
                conn.execute(
                    'UPDATE pinned_commands SET pin_order = ? WHERE machine_id = ? AND command = ?',
                    (index, machine_id_text, item['command']),
                )
        return True
