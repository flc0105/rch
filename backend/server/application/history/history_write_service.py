"""Activity mutations; Quick History has an independent lifecycle and store."""
from server.models.artifact import ArtifactReference
from core.protocol.references import ReferenceType, entity_reference
from core.utils.json_utils import compact_json_dumps
from server.models.records import OutputRecordBase



class HistoryWriteService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _machine_id(machine_id):
        return str(machine_id or '').strip() or 'unknown_machine'

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
            'result': {'output_records': []},
            'summary': activity['summary'],
            'created_at': activity.get('created_at') or when,
            'started_at': when, 'finished_at': None, 'references': list(activity.get('references', [])),
        }
        with self.store._lock, self.store.database.transaction():
            self.store._insert_entry(entry)
        return activity_id

    def interrupt_orphaned_activities(self):
        """Mark unfinished Activity records from a previous Server process as interrupted."""
        with self.store._lock, self.store.database.transaction():
            rows = self.store.database.connection().execute(
                "SELECT machine_id, activity_id FROM activity_records "
                "WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                entry = self.store._get_entry(row['machine_id'], row['activity_id'])
                if not entry:
                    continue
                records = entry['result'].setdefault('output_records', [])
                if len(records) < self.store.MAX_OUTPUT_RECORDS and sum(len(r['text']) for r in records) + len('Server restarted') <= self.store.MAX_OUTPUT_RECORD_CHARS:
                    records.append(OutputRecordBase(seq=len(records)+1, status=0, text='Server restarted', eof=1, created_at=self.store._now_iso()).to_dict())
                entry['status'] = 'interrupted'
                entry['finished_at'] = self.store._now_iso()
                self.store._update_entry(entry)

    def append_output_for_connection(self, conn, entry_id, status, text, eof=0, *, active_only=False):
        if conn is None or not entry_id:
            return
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(self.store._get_machine_id_from_conn(conn), entry_id)
            if entry is None or (active_only and entry['status'] not in {'running', 'cancelling'}):
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
            snapshot = ArtifactReference.from_dict(file_info).to_dict()
            if not snapshot['artifact_id']:
                return
            ref = {**entity_reference(ReferenceType.ARTIFACT, snapshot['artifact_id']), 'snapshot': snapshot}
            self._add_reference(entry, ref)
            self.store._update_entry(entry)

    @staticmethod
    def _add_reference(entry, reference):
        refs = entry['references']
        for ref in refs:
            if ref['type'] == reference['type'] and ref['id'] == reference['id']:
                if 'snapshot' in reference:
                    ref['snapshot'] = reference['snapshot']
                return
        refs.append(reference)

    def add_references(self, conn, entry_id, references):
        if not conn or not entry_id or not isinstance(references, list):
            return
        with self.store._lock, self.store.database.transaction():
            entry = self.store._get_entry(self.store._get_machine_id_from_conn(conn), entry_id)
            if entry is None:
                return
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                try:
                    ref = entity_reference(reference.get('type'), reference.get('id'))
                except ValueError:
                    continue
                self._add_reference(entry, ref)
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

    def clear_history_by_machine_id(self, machine_id, *, query=''):
        machine_id = self._machine_id(machine_id)
        if str(query or '').strip():
            self.store.quick_store.clear(machine_id, query=query)
        else:
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

    def clear_execution_history_by_machine_id(self, machine_id, *, query='', kind='', errors=False):
        machine_id = self._machine_id(machine_id)
        # Reuse the same filters as Activity Center's list/count queries.
        clauses, params = self.store._activity_filters(machine_id, query=query, kind=kind, errors=errors)
        with self.store._lock, self.store.database.transaction():
            cursor = self.store.database.connection().execute(
                f"DELETE FROM activity_records WHERE {' AND '.join(clauses)}", tuple(params))
            return cursor.rowcount

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
