"""Persist user-initiated transfers once; leave live progress in TransferService."""
import logging
import threading
import uuid

logger = logging.getLogger(__name__)


class TransferActivityRecorder:
    TERMINAL = {'completed': 'success', 'failed': 'error', 'cancelled': 'cancelled'}

    def __init__(self, history_store, transfer_service):
        self.store = history_store
        self.transfer_service = transfer_service
        self._tracked = {}
        self._lock = threading.RLock()
        # TransferService is memory-only; no transfer survives a Server restart.
        with self.store._lock, self.store.database.transaction():
            self.store.database.connection().execute("""
                UPDATE activity_records SET status = 'interrupted', finished_at = ?
                WHERE kind = 'transfer' AND status = 'running'
            """, (self.store._now_iso(),))

    def track(self, transfer_id, conn, *, action, origin, arguments, activity_id=''):
        if conn is None or not transfer_id:
            return ''
        transfer = self.transfer_service.get_transfer(transfer_id)
        if transfer is None:
            return ''
        entry_id = activity_id or uuid.uuid4().hex
        details = {k: v for k, v in dict(arguments).items()
                   if k in {'filename', 'paths', 'path', 'destination_path', 'count', 'source', 'size', 'input'}}
        invocation = {'arguments': details}
        if details.get('input'):
            invocation['input'] = details.pop('input')
        record = {
            'kind': 'transfer', 'action': action, 'origin': origin,
            'presentation': 'terminal' if origin in {'cli', 'web_terminal'} else 'none',
            'invocation': invocation,
            'resolved': {'transfer_id': transfer_id, 'direction': transfer.get('direction') or ''},
            'created_at': self.store._now_iso(),
        }
        with self._lock:
            if transfer_id in self._tracked:
                return self._tracked[transfer_id][1]
            try:
                self.store.write_service.create_activity_for_dispatch(conn, entry_id, record)
            except Exception:
                logger.exception('Failed to record transfer Activity')
                return ''
            self._tracked[transfer_id] = (conn, entry_id)
        # The transfer can finish between creation and registration.
        self.on_update(self.transfer_service.get_transfer(transfer_id) or transfer)
        return entry_id

    def on_update(self, transfer):
        state = str(transfer.get('state') or '').strip()
        if state not in self.TERMINAL:
            return
        transfer_id = str(transfer.get('transfer_id') or '')
        with self._lock:
            pair = self._tracked.pop(transfer_id, None)
        if pair is None:
            return
        conn, entry_id = pair
        status = self.TERMINAL[state]
        name = str(transfer.get('filename') or 'file')
        count = int((transfer.get('metadata') or {}).get('source_count') or 1)
        size = transfer.get('total_bytes')
        if status == 'success':
            message = f'Transferred {count} items' if count > 1 else f'Transferred {name}'
            if isinstance(size, int):
                message += f' ({size} bytes)'
        else:
            message = str(transfer.get('error') or ('Transfer cancelled' if status == 'cancelled' else 'Transfer failed'))
        try:
            self.store.write_service.append_output_for_connection(conn, entry_id, int(status == 'success'), message)
            artifact_id = str(transfer.get('artifact_id') or '')
            artifact_service = self.store.artifact_service
            if artifact_id and artifact_service is not None:
                artifact = artifact_service.get_artifact_by_id(artifact_id)
                if isinstance(artifact, dict) and artifact.get('artifact_id'):
                    self.store.write_service.append_file_for_connection(conn, entry_id, artifact)
            self.store.write_service.update_entry_status_for_connection(conn, entry_id, status)
        except Exception:
            logger.exception('Failed to finalize transfer Activity')
