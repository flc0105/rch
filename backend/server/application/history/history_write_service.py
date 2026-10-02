from server.models.artifact import ArtifactReference


class HistoryWriteService:
    """SQLite-backed command history mutation service."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _normalize_lookup_machine_id(machine_id: str) -> str:
        return str(machine_id or '').strip() or 'unknown_machine'

    def create_entry_for_connection(self, conn, command: str, source: str = 'cli'):
        if conn is None:
            return ''
        command_text = str(command or '').strip()
        if not command_text:
            return ''

        with self.store._lock, self.store.database.transaction():
            entry = self.store._build_entry(conn, command_text, source)
            self.store._insert_entry(entry)
            self.store._upsert_recent(entry, increment_use=True)
            return entry['entry_id']

    def append_output_for_connection(self, conn, entry_id: str, status: int, text: str, eof: int = 0):
        if conn is None or not entry_id:
            return

        machine_id = self.store._get_machine_id_from_conn(conn)
        output_text = self.store._safe_text(text)

        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(machine_id, entry_id)
            if entry is None:
                return

            entry['has_output'] = bool(entry.get('has_output')) or bool(output_text)
            entry['output_chunk_count'] = int(entry.get('output_chunk_count', 0) or 0) + 1
            entry['output_line_count'] = int(entry.get('output_line_count', 0) or 0) + self.store._count_output_lines(output_text)
            entry['output_char_count'] = int(entry.get('output_char_count', 0) or 0) + len(output_text)

            records = entry.setdefault('output_records', [])
            stored_char_count = int(entry.get('output_stored_char_count', 0) or 0)
            remaining_chars = max(self.store.MAX_OUTPUT_RECORD_CHARS - stored_char_count, 0)
            next_seq = int(entry.get('output_record_seq', 0) or 0) + 1
            entry['output_record_seq'] = next_seq

            if output_text and remaining_chars > 0 and len(records) < self.store.MAX_OUTPUT_RECORDS:
                stored_text = output_text[:remaining_chars]
                if len(stored_text) < len(output_text):
                    entry['output_truncated'] = True
                records.append({
                    'seq': next_seq,
                    'status': status,
                    'text': stored_text,
                    'time': self.store._now_text(),
                    'eof': eof,
                })
                entry['output_stored_char_count'] = stored_char_count + len(stored_text)
            elif output_text:
                entry['output_truncated'] = True

            entry['output_summary'] = self.store._build_output_summary(entry)
            self.store._update_entry(entry)
            self.store._update_recent_snapshot_if_present(entry)

    def append_file_for_connection(self, conn, entry_id: str, file_info: dict):
        if conn is None or not entry_id or not isinstance(file_info, dict):
            return

        machine_id = self.store._get_machine_id_from_conn(conn)
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(machine_id, entry_id)
            if entry is None:
                return

            files = entry.setdefault('files', [])
            files.append(ArtifactReference.from_dict(file_info).to_dict())
            entry['has_files'] = True
            entry['file_count'] = len(files)
            entry['output_summary'] = self.store._build_output_summary(entry)
            self.store._update_entry(entry)
            self.store._update_recent_snapshot_if_present(entry)

    def update_entry_command_for_connection(self, conn, entry_id: str, command: str):
        if conn is None or not entry_id:
            return False
        command_text = str(command or '').strip()
        if not command_text:
            return False

        machine_id = self.store._get_machine_id_from_conn(conn)
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(machine_id, entry_id)
            if entry is None:
                return False
            old_command = str(entry.get('command') or '').strip()
            if old_command == command_text:
                return False

            entry['command'] = command_text
            if not str(entry.get('raw_command') or '').strip():
                entry['raw_command'] = old_command
            self.store._update_entry(entry)
            self.store._rebuild_recent_for_command(machine_id, old_command)
            self.store._rebuild_recent_for_command(machine_id, command_text)
            return True

    def update_entry_status_for_connection(self, conn, entry_id: str, status: str, cwd_end: str = ''):
        if conn is None or not entry_id:
            return

        machine_id = self.store._get_machine_id_from_conn(conn)
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(machine_id, entry_id)
            if entry is None:
                return

            entry['status'] = status
            entry['final_status'] = status
            entry['finished_at'] = self.store._now_text()
            entry['cwd_end'] = (
                cwd_end
                or getattr(getattr(conn, 'session_info', None), 'cwd', '')
                or entry.get('cwd_end', '')
            )
            entry['time'] = entry.get('time') or self.store._now_text()
            self.store._update_duration(entry)
            entry['output_summary'] = self.store._build_output_summary(entry)
            self.store._update_entry(entry)
            self.store._update_recent_snapshot_if_present(entry)

    def clear_history_for_connection(self, conn):
        if conn is None:
            return
        self.clear_history_by_machine_id(self.store._get_machine_id_from_conn(conn))

    def clear_history_by_machine_id(self, machine_id: str):
        machine_id_text = self._normalize_lookup_machine_id(machine_id)
        with self.store._lock:
            self.store._clear_execution_history(machine_id_text)

    def set_command_pinned_for_connection(self, conn, command: str, is_pinned: bool):
        if conn is None:
            return False
        return self.set_command_pinned_by_machine_id(
            self.store._get_machine_id_from_conn(conn),
            command,
            is_pinned,
        )

    def set_command_pinned_by_machine_id(self, machine_id: str, command: str, is_pinned: bool):
        command_text = str(command or '').strip()
        if not command_text:
            return False
        machine_id_text = self._normalize_lookup_machine_id(machine_id)
        with self.store._lock:
            latest_entry = self.store._get_latest_entry_for_command(machine_id_text, command_text)
            return self.store.pinned_store.set_command_pinned(
                machine_id_text,
                command_text,
                bool(is_pinned),
                seed_entry=latest_entry,
            )

    def move_pinned_command_for_connection(self, conn, command: str, direction: str):
        if conn is None:
            return False
        return self.move_pinned_command_by_machine_id(
            self.store._get_machine_id_from_conn(conn),
            command,
            direction,
        )

    def move_pinned_command_by_machine_id(self, machine_id: str, command: str, direction: str):
        machine_id_text = self._normalize_lookup_machine_id(machine_id)
        return self.store.pinned_store.move_pinned_command(machine_id_text, command, direction)

    def delete_execution_entry_for_connection(self, conn, entry_id: str):
        if conn is None:
            return False
        return self.delete_execution_entry_by_machine_id(
            self.store._get_machine_id_from_conn(conn),
            entry_id,
        )

    def delete_execution_entry_by_machine_id(self, machine_id: str, entry_id: str):
        target_entry_id = str(entry_id or '').strip()
        if not target_entry_id:
            return False
        machine_id_text = self._normalize_lookup_machine_id(machine_id)
        with self.store._lock, self.store.database.transaction():
            return self.store._delete_execution(machine_id_text, target_entry_id)
