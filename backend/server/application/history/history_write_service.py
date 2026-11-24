"""Activity mutations; Quick History has an independent lifecycle and store."""
import json

from server.models.artifact import ArtifactReference
from core.protocol.message_types import MSG_TYPE_RESULT
from core.protocol.references import ReferenceType, entity_reference
from core.utils.command_output import ResultEventType
from server.config.config import COMMAND_HISTORY_MAX_RESULT_FIELD_BYTES


class HistoryWriteService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _machine_id(machine_id):
        return str(machine_id or '').strip() or 'unknown_machine'

    def create_activity_for_dispatch(self, conn, activity_id, activity):
        info = getattr(conn, 'session_info', None)
        when = self.store.now_iso()
        entry = {
            'activity_id': activity_id,
            'machine_id': self.store.machine_id_for_connection(conn),
            'client_id': getattr(info, 'client_id', '') or '',
            'kind': activity['kind'], 'action': activity['action'],
            'origin': activity['origin'], 'presentation': activity['presentation'],
            'status': 'running', 'invocation': dict(activity['invocation']),
            'resolved': dict(activity['resolved']),
            'summary': activity['summary'],
            'created_at': activity.get('created_at') or when,
            'started_at': when, 'finished_at': None, 'references': list(activity.get('references', [])),
        }
        with self.store.transaction():
            self.store.insert_entry(entry)
        return activity_id

    def interrupt_orphaned_activities(self):
        """Finish Activity records left active by a previous Server process."""
        with self.store.transaction():
            self.store.interrupt_active(self.store.now_iso())

    @staticmethod
    def _size_within(parts, remaining):
        size = 0
        for part in parts:
            if len(part) > remaining - size:
                return None
            size += len(part.encode('utf-8'))
            if size > remaining:
                return None
        return size

    def append_client_result(self, conn, entry_id, event):
        if (conn is None or not entry_id or event.get('type') != MSG_TYPE_RESULT
                or event.get('event_type') not in ResultEventType._value2member_map_):
            return
        machine_id = self.store.machine_id_for_connection(conn)
        with self.store.transaction():
            row = self.store.get_active_result_stats(machine_id, entry_id)
            if row is None:
                return

            result = dict(event)
            omitted = bool(row['result_omitted'])
            message_bytes = row['result_message_bytes']
            data_bytes = row['result_data_bytes']
            limit = COMMAND_HISTORY_MAX_RESULT_FIELD_BYTES
            # Omit an oversized field without changing the wire packet or other retained fields.
            if 'message' in result:
                size = self._size_within((result['message'],), max(0, limit - message_bytes))
                if size is None:
                    del result['message']
                    omitted = True
                else:
                    message_bytes += size
            if 'data' in result:
                encoder = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'))
                size = self._size_within(encoder.iterencode(result['data']), max(0, limit - data_bytes))
                if size is None:
                    del result['data']
                    omitted = True
                else:
                    data_bytes += size

            summary = row['result_summary']
            if result['event_type'] == 'completed':
                text = result.get('message', '').strip()
                summary = text if text and len(text) <= 256 and '\n' not in text and '\r' not in text else ''
            # Append the packet and its Server history time at the same array index.
            self.store.append_result(
                machine_id, entry_id, result, self.store.now_iso(),
                message_bytes=message_bytes, data_bytes=data_bytes,
                omitted=omitted, summary=summary)

    def append_file_for_connection(self, conn, entry_id, file_info):
        if conn is None or not entry_id or not isinstance(file_info, dict):
            return
        with self.store.transaction():
            entry = self.store.get_entry(self.store.machine_id_for_connection(conn), entry_id)
            if entry is None:
                return
            snapshot = ArtifactReference.from_dict(file_info).to_dict()
            if not snapshot['artifact_id']:
                return
            ref = {**entity_reference(ReferenceType.ARTIFACT, snapshot['artifact_id']), 'snapshot': snapshot}
            self._add_reference(entry, ref)
            self.store.update_entry(entry)

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
        with self.store.transaction():
            entry = self.store.get_entry(self.store.machine_id_for_connection(conn), entry_id)
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
            self.store.update_entry(entry)

    def update_entry_status_for_connection(self, conn, entry_id, status, cwd_end=''):
        if conn is None or not entry_id:
            return
        with self.store.transaction():
            entry = self.store.get_entry(self.store.machine_id_for_connection(conn), entry_id)
            if entry is None:
                return
            if entry['status'] in {'success', 'partial', 'error', 'cancelled', 'interrupted', 'timed_out', 'stopped'}:
                return
            entry['status'] = status
            if status in {'success', 'partial', 'error', 'cancelled', 'interrupted', 'timed_out', 'stopped'}:
                entry['finished_at'] = self.store.now_iso()
            self.store.update_entry(entry)

    def clear_history_for_connection(self, conn):
        if conn is not None:
            self.clear_history_by_machine_id(self.store.machine_id_for_connection(conn))

    def clear_history_by_machine_id(self, machine_id, *, query=''):
        machine_id = self._machine_id(machine_id)
        if str(query or '').strip():
            self.store.quick_store.clear(machine_id, query=query)
        else:
            self.store.quick_store.clear(machine_id)

    def set_command_pinned_for_connection(self, conn, command, is_pinned):
        if conn is None:
            return False
        return self.set_command_pinned_by_machine_id(self.store.machine_id_for_connection(conn), command, is_pinned)

    def set_command_pinned_by_machine_id(self, machine_id, command, is_pinned):
        command = str(command or '').strip()
        if not command:
            return False
        machine_id = self._machine_id(machine_id)
        return self.store.pinned_store.set_command_pinned(machine_id, command, bool(is_pinned))

    def move_pinned_command_by_machine_id(self, machine_id, command, direction):
        return self.store.pinned_store.move_pinned_command(self._machine_id(machine_id), command, direction)

    def clear_execution_history_by_machine_id(self, machine_id, *, query='', kind='', errors=False):
        machine_id = self._machine_id(machine_id)
        return self.store.delete_activities(machine_id, query=query, kind=kind, errors=errors)

    def delete_execution_entry_for_connection(self, conn, entry_id):
        if conn is None:
            return False
        return self.delete_execution_entry_by_machine_id(self.store.machine_id_for_connection(conn), entry_id)

    def delete_execution_entry_by_machine_id(self, machine_id, entry_id):
        machine_id, entry_id = self._machine_id(machine_id), str(entry_id or '').strip()
        if not entry_id:
            return False
        # Deleting an Activity must not mutate Quick History or Pins.
        return self.store.delete_activity(machine_id, entry_id)
