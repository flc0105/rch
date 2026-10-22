"""Activity mutations; Quick History has an independent lifecycle and store."""
from server.models.artifact import ArtifactReference
from server.models.records import OutputRecordBase


class HistoryWriteService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _machine_id(machine_id):
        return str(machine_id or '').strip() or 'unknown_machine'

    def create_entry_for_connection(self, conn, command, source='cli'):
        # Public history creation runs through the orchestrator dispatch boundary.
        return ''

    def create_activity_for_dispatch(self, conn, activity_id, activity):
        info = getattr(conn, 'session_info', None)
        when = self.store._now_iso()
        entry = {
            'activity_id': activity_id,
            'machine_id': self.store._get_machine_id_from_conn(conn),
            'client_id': getattr(info, 'client_id', '') or '',
            'kind': activity['kind'], 'action': activity['action'],
            'origin': activity['origin'], 'presentation': activity['presentation'],
            'status': 'running', 'invocation': dict(activity['invocation']),
            'resolved': dict(activity['resolved']),
            'result': {'truncated': False, 'output_records': []},
            'created_at': activity.get('created_at') or when,
            'started_at': when, 'finished_at': None, 'files': [],
        }
        with self.store._lock, self.store.database.transaction():
            self.store._insert_entry(entry)
        return activity_id

    def set_background_job_result(self, conn, entry_id, result):
        """Attach bounded, non-sensitive Job identity and batch counts only."""
        if conn is None or not entry_id:
            return
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(self.store._get_machine_id_from_conn(conn), entry_id)
            if not entry or entry['kind'] != 'background_job':
                return
            resolved = entry['resolved']
            if result.get('job_id'):
                resolved['job_id'] = str(result['job_id'])
            if entry['action'] == 'stop_all_jobs':
                resolved['job_ids'] = [str(item) for item in result.get('job_ids', [])]
                for key in ('total', 'succeeded', 'failed'):
                    resolved[key] = int(result.get(key, 0))
                # Avoid full parameters and unbounded error output in Activity.
                resolved['errors'] = [str(error)[:250] for error in result.get('errors', [])[:20]]
            self.store._update_entry(entry)

    def append_output_for_connection(self, conn, entry_id, status, text, eof=0):
        if conn is None or not entry_id:
            return
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(self.store._get_machine_id_from_conn(conn), entry_id)
            if entry is None:
                return
            result = entry['result']
            records = result.setdefault('output_records', [])
            total_chars = sum(len(str(record.get('text') or '')) for record in records)
            remaining = max(0, self.store.MAX_OUTPUT_RECORD_CHARS - total_chars)
            output = self.store._safe_text(text)
            if output and remaining and len(records) < self.store.MAX_OUTPUT_RECORDS:
                saved = output[:remaining]
                records.append(OutputRecordBase(seq=len(records) + 1, status=int(status or 0), text=saved,
                                                eof=int(eof or 0), created_at=self.store._now_iso()).to_dict())
                if len(saved) < len(output):
                    result['truncated'] = True
            elif output:
                result['truncated'] = True
            self.store._update_entry(entry)

    def append_file_for_connection(self, conn, entry_id, file_info):
        if conn is None or not entry_id or not isinstance(file_info, dict):
            return
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(self.store._get_machine_id_from_conn(conn), entry_id)
            if entry is None:
                return
            entry['files'].append(ArtifactReference.from_dict(file_info).to_dict())
            self.store._update_entry(entry)

    def update_entry_status_for_connection(self, conn, entry_id, status, cwd_end=''):
        if conn is None or not entry_id:
            return
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(self.store._get_machine_id_from_conn(conn), entry_id)
            if entry is None:
                return
            if entry['status'] in {'success', 'error', 'cancelled', 'interrupted', 'timed_out', 'stopped'}:
                return
            entry['status'] = status
            if status in {'success', 'error', 'cancelled', 'interrupted', 'timed_out', 'stopped'}:
                entry['finished_at'] = self.store._now_iso()
            self.store._update_entry(entry)

    def clear_history_for_connection(self, conn):
        if conn is not None:
            self.clear_history_by_machine_id(self.store._get_machine_id_from_conn(conn))

    def clear_history_by_machine_id(self, machine_id):
        machine_id = self._machine_id(machine_id)
        self.store.quick_store.clear(machine_id)

    def set_command_pinned_for_connection(self, conn, command, is_pinned):
        if conn is None:
            return False
        return self.set_command_pinned_by_machine_id(self.store._get_machine_id_from_conn(conn), command, is_pinned)

    def set_command_pinned_by_machine_id(self, machine_id, command, is_pinned):
        command = str(command or '').strip()
        if not command:
            return False
        machine_id = self._machine_id(machine_id)
        with self.store._lock:
            return self.store.pinned_store.set_command_pinned(machine_id, command, bool(is_pinned))

    def move_pinned_command_by_machine_id(self, machine_id, command, direction):
        return self.store.pinned_store.move_pinned_command(self._machine_id(machine_id), command, direction)

    def delete_execution_entry_for_connection(self, conn, entry_id):
        if conn is None:
            return False
        return self.delete_execution_entry_by_machine_id(self.store._get_machine_id_from_conn(conn), entry_id)

    def delete_execution_entry_by_machine_id(self, machine_id, entry_id):
        machine_id, entry_id = self._machine_id(machine_id), str(entry_id or '').strip()
        if not entry_id:
            return False
        with self.store._lock, self.store.database.transaction():
            cursor = self.store.database.connection().execute(
                'DELETE FROM activity_records WHERE machine_id = ? AND activity_id = ?',
                (machine_id, entry_id))
            # Deleting an Activity must not mutate Quick History or Pins.
            return cursor.rowcount > 0
