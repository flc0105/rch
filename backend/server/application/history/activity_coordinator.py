"""One authoritative Activity lifecycle; adapters provide operation intents and events."""
import threading
import uuid

from server.application.history.activity_definitions import ActivityKind


class ActivityCoordinator:
    def __init__(self, history_store):
        self.history_store = history_store
        self.quick_store = history_store.quick_store
        self._pending = {}
        self._lock = threading.RLock()

    def prepare(self, conn, operation, *, entry_id='', quick_command=None):
        """Prepare one Activity without writing it. An actual Client dispatch commits it."""
        if conn is None or operation is None:
            return ''
        if operation.kind not in ActivityKind.ALL:
            raise ValueError('Invalid Activity kind')
        activity_id = entry_id or uuid.uuid4().hex
        with self._lock:
            previous = self._pending.get(activity_id)
            if previous is not None and previous['conn'] is not conn:
                return ''
            if quick_command is not None:
                self.quick_store.begin(activity_id, conn, quick_command)
            self._pending[activity_id] = {
                'conn': conn, 'kind': operation.kind, 'action': operation.action,
                'origin': previous['origin'] if previous and operation.reuse_origin else operation.origin,
                'presentation': previous['presentation'] if previous and operation.reuse_origin else operation.presentation,
                'invocation': operation.invocation(), 'resolved': dict(operation.resolved),
                'created_at': previous['created_at'] if previous else self.history_store._now_iso(),
            }
        return activity_id

    def pending(self, conn, entry_id):
        with self._lock:
            entry = self._pending.get(entry_id)
            return entry if entry is not None and entry['conn'] is conn else None

    def mutate_pending(self, conn, entry_id, fn):
        with self._lock:
            pending = self._pending.get(entry_id)
            if pending is not None and pending['conn'] is conn:
                fn(pending)

    def dispatch(self, conn, entry_id, *, command='', command_type='command'):
        if not entry_id:
            return False
        with self._lock:
            pending = self._pending.get(entry_id)
            if pending is None or pending['conn'] is not conn:
                return False
            self._pending.pop(entry_id)
        if command_type == 'script':
            pending['resolved'].pop('command', None)
        elif not pending['resolved']:
            pending['resolved'] = {'command_type': command_type, 'command': command}
        self.history_store.write_service.create_activity_for_dispatch(conn, entry_id, pending)
        return True

    def details(self, conn, entry_id, values):
        if entry_id and isinstance(values, dict) and values:
            self.history_store.write_service.update_activity_resolved(conn, entry_id, values)

    def drop(self, entry_id):
        with self._lock:
            self._pending.pop(entry_id, None)

    def claim_upload(self, conn, entry_id):
        """Transfer takes ownership of an existing terminal upload Activity ID."""
        def is_upload(row):
            return (row and row['conn'] is conn and
                    row['kind'] == ActivityKind.COMMAND)
        with self._lock:
            pending = self._pending.get(entry_id)
            if is_upload(pending):
                self._pending.pop(entry_id)
                return pending['origin'], pending['invocation']['input']
        return None

    def discard(self, conn, entry_id):
        self.quick_store.discard(entry_id)
        with self._lock:
            return self._pending.pop(entry_id, None) is not None

    def append_output(self, conn, entry_id, status, text, eof=0):
        self.history_store.append_output_for_connection(conn, entry_id, status, text, eof)

    def append_request_output(self, conn, entry_id, status, text, eof=0):
        self.history_store.write_service.append_output_for_connection(conn, entry_id, status, text, eof, request_owned=True)

    def update_status(self, conn, entry_id, status):
        if entry_id:
            self.history_store.update_entry_status_for_connection(conn, entry_id, status)

    def finish(self, conn, entry_id, ok, cwd_end='', status=''):
        with self._lock:
            self._pending.pop(entry_id, None)
        if not entry_id:
            return
        final_status = status or ('success' if ok else 'error')
        # Quick status is saved regardless of whether an Activity was dispatched.
        self.quick_store.finish(entry_id, final_status)
        self.history_store.update_entry_status_for_connection(conn, entry_id, final_status, cwd_end=cwd_end)

    def bind_command_entry(self, conn, command_id, entry_id):
        if conn is None or not command_id or not entry_id:
            return
        try:
            conn.bind_history_entry(command_id, entry_id)
        except Exception:
            pass

    def get_bound_entry_id(self, conn, command_id):
        try:
            return conn.get_history_entry_id(command_id)
        except Exception:
            return ''

    def clear_command_entry(self, conn, command_id):
        try:
            conn.clear_history_entry(command_id)
        except Exception:
            pass

    def bind_uploaded_artifact(self, conn, source_command_id, artifact):
        if conn is None or source_command_id is None or not isinstance(artifact, dict) or not artifact:
            return False
        entry_id = self.get_bound_entry_id(conn, source_command_id)
        if not entry_id:
            return False
        self.history_store.append_file_for_connection(conn, entry_id, artifact)
        return True
