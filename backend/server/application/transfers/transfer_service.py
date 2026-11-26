import threading
import time
import uuid

from server.application.transfers.transfer_history_store import TransferHistoryStore
from server.application.transfers.transfer_batch_store import TransferBatchStore
from server.application.transfers.upload_plan import remote_upload_members
from datetime import datetime
from core.transfer_settings import FileTransferMode
from core.protocol.message_types import MSG_TYPE_TRANSFER_CANCEL


class TransferService:
    """
    Active transfers stay in memory for progress and cancellation. Durable
    transfer facts live in rch.db; only start and terminal changes write SQLite.
    SSE remains scoped to the initiating browser tab.
    """

    TERMINAL_STATES = {'completed', 'failed', 'cancelled', 'interrupted'}
    MEMORY_RECENT_CACHE_SIZE = 128

    def __init__(self, event_bus, database):
        self.event_bus = event_bus
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._items = {}
        self._recent_ids = []
        self._batch_tasks = {}
        self.lifecycle_adapter = None
        self.terminal_callback = None
        self.tcp_transport = None
        self.history = TransferHistoryStore(database)
        self.batches = TransferBatchStore(database, self.history)

    def start_batch(self, *, batch_id, client_id, tab_id, destination_path, files, directories):
        plan, members = remote_upload_members(destination_path, files, directories)
        total_files = len(plan.files)
        with self._changed:
            batch = self.batches.start(batch_id=batch_id, client_id=client_id,
                                       tab_id=tab_id, destination_path=destination_path,
                                       total_files=total_files, directories=plan.directories, members=members)
            self._publish_batch(batch)
        return batch

    def recover_batch_submission(self, *, batch_id, client_id, tab_id, destination_path, files, directories):
        plan, members = remote_upload_members(destination_path, files, directories)
        with self._lock:
            batch = self.batches.get(batch_id)
            if not batch:
                return None
            if (batch['client_id'], batch['tab_id'], batch['destination_path']) != (client_id, tab_id, destination_path):
                raise ValueError('Upload batch not found or mismatched')
            if batch['state'] != 'running' or not self.batches.matches_plan(batch_id, members, plan.directories):
                raise ValueError('Upload batch is closed or its plan changed; check Transfers')
            task_id = self._batch_tasks.get(batch_id)
            if not task_id:
                raise ValueError('Upload batch submission is not confirmed; check Transfers')
            return {**batch, 'task_id': task_id}

    def finalize_batch(self, *, batch_id, client_id, tab_id, folder_count, error):
        with self._changed:
            before = self.batches.get(batch_id)
            batch = self.batches.finalize(batch_id, client_id=client_id, tab_id=tab_id,
                                          folder_count=folder_count, error=error)
            self._publish_batch_transition(before, batch)
            return batch

    def _refresh_batch(self, batch_id):
        with self._changed:
            before = self.batches.get(batch_id)
            batch = self.batches.refresh(batch_id)
            self._publish_batch_transition(before, batch)

    def _publish_batch_transition(self, before, batch):
        if not batch:
            return
        self._publish_batch(batch)
        if before and before['state'] == 'running' and batch['state'] != 'running':
            self._batch_tasks.pop(batch['batch_id'], None)
            self._publish_batch_complete(batch)
        self._changed.notify_all()

    def get_batch(self, batch_id):
        with self._lock:
            return self.batches.get(batch_id)

    def bind_batch_task(self, batch_id, task_id):
        with self._lock:
            batch = self.batches.get(batch_id)
            if batch and batch['state'] == 'running':
                self._batch_tasks[batch_id] = task_id

    def request_batch_cancellation(self, batch_id, *, tab_id=''):
        with self._changed:
            before = self.batches.get(batch_id)
            if not before or not tab_id or before['tab_id'] != tab_id:
                raise ValueError('Upload batch not found')
            batch = self.batches.request_cancel(batch_id)
            self._publish_batch_transition(before, batch)
            return batch, self.list_batch_members(batch_id, tab_id)

    def expire_idle_batch(self, batch_id, timeout=300):
        """Close abandoned submissions; active transfers keep their native lifecycle."""
        with self._changed:
            batch = self.batches.get(batch_id)
            if not batch or batch['state'] != 'running':
                return batch
            members = self.list_batch_members(batch_id)
            now = datetime.now()
            def idle(item):
                return (now - datetime.fromisoformat(item.get('updated_at') or item['started_at'])).total_seconds() >= timeout
            expired = [member for member in members if member['state'] == 'running'
                       and member['stage'] in ('uploading_to_server', 'preparing') and idle(member)]
            abandoned = not batch['active_files'] and not batch['submission_closed'] and all(idle(x) for x in [batch, *members])
            if expired or abandoned:
                error = 'Browser upload submission timed out'
                self.finalize_batch(batch_id=batch_id, client_id=batch['client_id'], tab_id=batch['tab_id'],
                                    folder_count=batch['folder_count'], error=error)
                for member in expired:
                    self.fail_transfer(member['transfer_id'], error)
                return self.batches.get(batch_id)
            return batch

    def _publish_batch(self, batch):
        self.event_bus.publish('transfer_batch_updated', {k: v for k, v in batch.items() if k != 'tab_id'},
                               target_tab_id=batch['tab_id'])

    def _publish_batch_complete(self, batch):
        self.event_bus.publish('file_transfer_batch_finished', {k: v for k, v in batch.items() if k != 'tab_id'},
                               target_tab_id=batch['tab_id'])

    def list_batch_members(self, batch_id, tab_id=''):
        with self._lock:
            batch = self.batches.get(str(batch_id or '').strip())
            if not batch or (tab_id and batch['tab_id'] != tab_id and batch['state'] == 'running'):
                raise ValueError('Upload batch not found')
            return [self._public_item(self._items[row['transfer_id']])
                    if row['transfer_id'] in self._items else row
                    for row in self.batches.members(batch_id)]

    def create_transfer(
        self,
        *,
        client_id: str,
        direction: str,
        filename: str = '',
        hostname: str = '',
        source_path: str = '',
        destination_path: str = '',
        tab_id: str = '',
        stage: str = 'preparing',
        metadata: dict | None = None,
        total_bytes=None,
        transfer_id=None,
        cancel_supported=True,
        progress_supported=True,
    ) -> dict:
        transfer_id = transfer_id or uuid.uuid4().hex
        now_iso = datetime.now().isoformat()
        now_mono = time.monotonic()

        item = {
            'transfer_id': transfer_id,
            'batch_id': str((metadata or {}).get('batch_id') or ''),
            'client_id': str(client_id or '').strip(),
            'direction': str(direction or '').strip(),
            'filename': str(filename or '').strip(),
            'hostname': str(hostname or '').strip(),
            'source_path': str(source_path or '').strip(),
            'destination_path': str(destination_path or '').strip(),
            'tab_id': str(tab_id or '').strip(),
            'state': 'running',
            'stage': str(stage or 'preparing').strip() or 'preparing',
            'total_bytes': self._normalize_int(total_bytes),
            'transferred_bytes': 0,
            'percent': None,
            'speed_bytes_per_sec': 0,
            'eta_seconds': None,
            'progress_supported': bool(progress_supported),
            'cancel_supported': bool(cancel_supported),
            'artifact_id': '',
            'error': '',
            'metadata': dict(metadata or {}),
            'started_at': now_iso,
            'updated_at': now_iso,
            'completed_at': '',
            '_last_progress_bytes': 0,
            '_last_progress_mono': now_mono,
            '_speed_ema': 0.0,
        }
        self._refresh_derived_fields(item)

        with self._changed:
            if item['batch_id']:
                self.batches.validate_member(item['batch_id'], client_id=item['client_id'],
                                             tab_id=item['tab_id'],
                                             total_files=int(item['metadata']['batch_total']),
                                             batch_index=int(item['metadata']['batch_index']),
                                             destination_path=item['destination_path'], filename=item['filename'],
                                             size=item['total_bytes'], conflict_policy=item['metadata'].get('conflict_policy', 'stop'))
            self.history.record_started(item)
            self._items[transfer_id] = item
            self._changed.notify_all()
            self._publish(item)
            self._publish_lifecycle(item, 'started')
            if item['batch_id']:
                self._publish_batch(self.batches.get(item['batch_id']))
        return self._public_item(item)

    def update_transfer(
        self,
        transfer_id: str,
        *,
        client_id: str = '',
        tab_id: str = '',
        expected_stage: str = '',
        **patch,
    ) -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return None

        with self._lock:
            item = self._items.get(normalized_id)
            if not item:
                return None

            normalized_client_id = str(client_id or '').strip()
            if normalized_client_id and item.get('client_id') and item.get('client_id') != normalized_client_id:
                return None

            normalized_tab_id = str(tab_id or '').strip()
            if normalized_tab_id and item.get('tab_id') and item.get('tab_id') != normalized_tab_id:
                return None

            normalized_expected_stage = str(expected_stage or '').strip()
            if normalized_expected_stage and str(item.get('stage') or '').strip() != normalized_expected_stage:
                return self._public_item(item)

            if item.get('state') in self.TERMINAL_STATES:
                return self._public_item(item)

            previous_state = str(item.get('state') or '').strip().lower()
            original = dict(item)
            if (item['stage'] == 'cancelling'
                    and item['metadata'].get('file_transfer_mode') == FileTransferMode.TCP_STREAMING.value
                    and patch.get('state') not in self.TERMINAL_STATES):
                patch.pop('stage', None)
            self._apply_patch(item, patch)
            self._refresh_derived_fields(item)
            next_state = str(item.get('state') or '').strip().lower()
            if next_state in self.TERMINAL_STATES:
                try:
                    self.history.record_terminal(item)
                except Exception:
                    item.clear()
                    item.update(original)
                    raise
            self._remember_if_terminal(item)
            snapshot = self._public_item(item)
            lifecycle = ''
            if previous_state not in self.TERMINAL_STATES and next_state in self.TERMINAL_STATES:
                lifecycle = 'error' if next_state == 'failed' else 'stopped'
            self._changed.notify_all()

            self._publish(item)
            if lifecycle and item['batch_id']:
                self._refresh_batch(item['batch_id'])
        if lifecycle:
            if self.terminal_callback is not None:
                self.terminal_callback(normalized_id)
            self._publish_lifecycle(item, lifecycle)
            if self.lifecycle_adapter is not None:
                self.lifecycle_adapter.transfer_updated(snapshot)
        return snapshot

    def update_progress(
        self,
        transfer_id: str,
        transferred_bytes,
        *,
        client_id: str = '',
        tab_id: str = '',
        stage: str = '',
        total_bytes=None,
        expected_stage: str = '',
    ) -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return None

        with self._lock:
            item = self._items.get(normalized_id)
            if not item:
                return None

            normalized_client_id = str(client_id or '').strip()
            if normalized_client_id and item.get('client_id') and item.get('client_id') != normalized_client_id:
                return None

            normalized_tab_id = str(tab_id or '').strip()
            if normalized_tab_id and item.get('tab_id') and item.get('tab_id') != normalized_tab_id:
                return None

            normalized_expected_stage = str(expected_stage or '').strip()
            if normalized_expected_stage and str(item.get('stage') or '').strip() != normalized_expected_stage:
                return self._public_item(item)

            if item.get('state') in self.TERMINAL_STATES:
                return self._public_item(item)

            incoming_bytes = self._normalize_int(transferred_bytes)
            current_bytes = self._normalize_int(item.get('transferred_bytes')) or 0
            patch = {
                'transferred_bytes': max(current_bytes, incoming_bytes or 0),
            }
            if stage:
                patch['stage'] = stage
            if total_bytes is not None:
                patch['total_bytes'] = total_bytes

            self._apply_patch(item, patch)
            self._refresh_derived_fields(item)
            snapshot = self._public_item(item)
            self._changed.notify_all()

            self._publish(item)
        return snapshot

    def reset_progress(
        self,
        transfer_id: str,
        *,
        client_id: str = '',
        tab_id: str = '',
        stage: str = '',
        total_bytes=None,
        **patch,
    ) -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return None

        with self._lock:
            item = self._items.get(normalized_id)
            if not item:
                return None

            normalized_client_id = str(client_id or '').strip()
            if normalized_client_id and item.get('client_id') and item.get('client_id') != normalized_client_id:
                return None

            normalized_tab_id = str(tab_id or '').strip()
            if normalized_tab_id and item.get('tab_id') and item.get('tab_id') != normalized_tab_id:
                return None

            if item.get('state') in self.TERMINAL_STATES:
                return self._public_item(item)

            now_mono = time.monotonic()
            item['transferred_bytes'] = 0
            item['percent'] = None
            item['speed_bytes_per_sec'] = 0
            item['eta_seconds'] = None
            item['_last_progress_bytes'] = 0
            item['_last_progress_mono'] = now_mono
            item['_speed_ema'] = 0.0

            next_patch = dict(patch or {})
            next_patch['state'] = 'running'
            next_patch['error'] = ''
            if stage:
                next_patch['stage'] = stage
            if total_bytes is not None:
                next_patch['total_bytes'] = total_bytes

            self._apply_patch(item, next_patch)
            self._refresh_derived_fields(item)
            snapshot = self._public_item(item)
            self._changed.notify_all()

            self._publish(item)
        return snapshot

    def wait_for_tcp_transfer(self, transfer_id, client_id, timeout=5):
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                item = self._items.get(transfer_id)
                if not item or item['client_id'] != client_id or item['state'] != 'running':
                    return None
                metadata = item['metadata']
                if metadata.get('transport') != 'client_transfer_manager' or metadata.get('browser_stage'):
                    return None
                mode = metadata.get('file_transfer_mode')
                if mode == FileTransferMode.TCP_STREAMING.value:
                    return self._public_item(item)
                if mode or time.monotonic() >= deadline:
                    return None
                self._changed.wait(max(0, deadline - time.monotonic()))

    def commit_tcp_artifact(self, transfer_id, client_id, filename, size, commit):
        # Serialize the final registration with cancel/disconnect and terminal updates.
        with self._changed:
            item = self._items.get(transfer_id)
            if not item or item['client_id'] != client_id or item['state'] != 'running':
                raise RuntimeError('File transfer is no longer active')
            if item['stage'] == 'cancelling':
                # Server owns this commit. Cancellation won before registration.
                self.cancel_transfer(transfer_id)
                raise RuntimeError('File transfer cancelled')
            artifact = commit()
            self.update_transfer(transfer_id, client_id=client_id, state='completed', stage='completed',
                                 artifact_id=artifact['artifact_id'], filename=filename,
                                 transferred_bytes=size, total_bytes=size, error='')
            return artifact

    def handle_client_update(self, client_id: str, payload: dict, *, session=None):
        if not isinstance(payload, dict):
            return None
        transfer_id = str(payload.get('transfer_id') or '').strip()
        if not transfer_id:
            return None

        allowed = {
            'state',
            'stage',
            'filename',
            'total_bytes',
            'transferred_bytes',
            'progress_supported',
            'cancel_supported',
            'artifact_id',
            'destination_path',
            'error',
            'metadata',
        }
        patch = {key: payload.get(key) for key in allowed if key in payload}
        updated = self.update_transfer(transfer_id, client_id=client_id, **patch)
        if (payload.get('data_ready') is True and session is not None and self.tcp_transport is not None
                and updated and updated['state'] == 'running'
                and updated['metadata'].get('file_transfer_mode') == FileTransferMode.TCP_STREAMING.value):
            self.tcp_transport.start_bind(session, transfer_id)
        return updated

    def fail_transfer(self, transfer_id: str, error: str, *, client_id: str = ''):
        return self.update_transfer(
            transfer_id,
            client_id=client_id,
            state='failed',
            stage='failed',
            error=str(error or '').strip(),
        )

    def complete_transfer(self, transfer_id: str, *, client_id: str = '', artifact_id: str = ''):
        patch = {
            'state': 'completed',
            'stage': 'completed',
            'error': '',
        }
        if artifact_id:
            patch['artifact_id'] = artifact_id
        return self.update_transfer(transfer_id, client_id=client_id, **patch)

    def find_active_transfer_by_task_id(self, task_id: str) -> dict | None:
        normalized_task_id = str(task_id or '').strip()
        if not normalized_task_id:
            return None
        with self._lock:
            for batch_id, bound_task in self._batch_tasks.items():
                if bound_task == task_id:
                    return self.batches.get(batch_id)
            for item in self._items.values():
                metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
                if item.get('state') == 'running' and str(metadata.get('task_id') or '').strip() == normalized_task_id:
                    return self._public_item(item)
        return None

    def list_active_transfers_for_client(self, client_id: str) -> list[dict]:
        normalized_client_id = str(client_id or '').strip()
        if not normalized_client_id:
            return []
        with self._lock:
            return [
                self._public_item(item)
                for item in self._items.values()
                if item.get('state') == 'running'
                and str(item.get('client_id') or '').strip() == normalized_client_id
            ]

    def fail_active_transfers_for_client(self, client_id: str, error: str = 'Client disconnected') -> int:
        with self._changed:
            for batch in self.batches.active(''):
                if batch['client_id'] == client_id:
                    self.finalize_batch(batch_id=batch['batch_id'], client_id=client_id,
                        tab_id=batch['tab_id'], folder_count=batch['folder_count'], error=error)
            active = self.list_active_transfers_for_client(client_id)
            failed = 0
            for item in active:
                updated = self.fail_transfer(item['transfer_id'], error, client_id=client_id)
                failed += bool(updated and updated['state'] == 'failed')
            return failed

    def cancel_operation(self, transfer_id, *, tab_id='', connection_lookup=None):
        if transfer_id.startswith('batch:'):
            batch, members = self.request_batch_cancellation(transfer_id[6:], tab_id=tab_id)
            dispatch = []
            for member in members:
                if member['state'] != 'running' or member.get('cancel_supported') is False:
                    continue
                try:
                    current, remote = self.request_cancellation(member['transfer_id'], tab_id=tab_id)
                except ValueError:
                    current = self.get_transfer(member['transfer_id'])
                    if current and current['state'] == 'running':
                        raise
                    continue
                if remote:
                    dispatch.append(current)
            errors = []
            for member in dispatch:
                try:
                    if connection_lookup is None:
                        raise RuntimeError('server is not available for transfer cancellation')
                    connection_lookup(member['client_id']).send({
                        'type': MSG_TYPE_TRANSFER_CANCEL, 'transfer_id': member['transfer_id']})
                except Exception as exc:
                    # A failed cancel send is not evidence that the Client stopped.
                    errors.append(str(exc))
            if errors:
                raise RuntimeError('Cancellation delivery failed: ' + '; '.join(errors))
            return self.get_batch(batch['batch_id'])
        current, dispatch = self.request_cancellation(transfer_id, tab_id=tab_id)
        if dispatch:
            if connection_lookup is None:
                raise RuntimeError('server is not available for transfer cancellation')
            connection_lookup(current['client_id']).send({
                'type': MSG_TYPE_TRANSFER_CANCEL, 'transfer_id': transfer_id})
        return self.get_transfer(transfer_id, tab_id=tab_id) or current

    def get_transfer(self, transfer_id: str, *, tab_id: str = '') -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        normalized_tab_id = str(tab_id or '').strip()
        if not normalized_id:
            return None

        with self._lock:
            item = self._items.get(normalized_id)
            if not item:
                return self.history.get(normalized_id)
            if item.get('state') not in self.TERMINAL_STATES and normalized_tab_id and item.get('tab_id') and item.get('tab_id') != normalized_tab_id:
                return None
            return self._public_item(item)

    def find_tab_transfer_by_metadata(self, tab_id, key, value):
        with self._lock:
            return next((self._public_item(item) for item in self._items.values()
                         if item['tab_id'] == tab_id and item['metadata'].get(key) == value), None)

    def get_tab_transfer(self, transfer_id: str, tab_id: str) -> dict | None:
        """Strict tab ownership for ephemeral submission/status APIs, including cached terminal items."""
        with self._lock:
            item = self._items.get(transfer_id)
            if not item or not tab_id or item['tab_id'] != tab_id:
                return None
            return self._public_item(item)

    def wait_for_terminal(self, transfer_id: str, timeout: float | None = None) -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return None

        deadline = None
        if timeout is not None:
            try:
                normalized_timeout = max(0.0, float(timeout))
            except Exception:
                normalized_timeout = 0.0
            deadline = time.monotonic() + normalized_timeout

        with self._changed:
            while True:
                item = self._items.get(normalized_id)
                if not item:
                    return self.history.get(normalized_id)
                if item.get('state') in self.TERMINAL_STATES:
                    return self._public_item(item)

                if deadline is None:
                    self._changed.wait()
                    continue

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._public_item(item)
                self._changed.wait(remaining)

    def wait_for_terminal_or_idle(self, transfer_id: str, idle_timeout=300):
        """Wait for a terminal state or a sustained lack of transfer updates."""
        with self._changed:
            while True:
                item = self._items.get(transfer_id)
                if not item:
                    return self.history.get(transfer_id)
                if item['state'] in self.TERMINAL_STATES:
                    return self._public_item(item)
                last_update = datetime.fromisoformat(item['updated_at'])
                remaining = idle_timeout - (datetime.now() - last_update).total_seconds()
                if remaining <= 0:
                    return self._public_item(item)
                self._changed.wait(remaining)

    def request_cancellation(self, transfer_id: str, *, tab_id: str = '') -> tuple[dict, bool]:
        """Atomically decide whether cancellation is local or needs Client dispatch."""
        with self._lock:
            current = self.get_transfer(transfer_id, tab_id=tab_id)
            if not current:
                raise ValueError('transfer not found')
            if current['state'] != 'running':
                raise ValueError('transfer is no longer active')
            if current.get('cancel_supported') is False:
                raise ValueError('current transfer mode does not support cancellation')
            stage = current['stage']
            if stage == 'cancelling':
                # A retry may be needed if the earlier main-channel send failed.
                # The Client's cancellation context is idempotent.
                return current, True
            metadata = current['metadata']
            # Browser staging ends when the managed Client transfer is dispatched.
            if stage == 'uploading_to_server' or (
                stage == 'preparing' and metadata.get('source') == 'remote_file_upload'
                and metadata.get('transport') != 'client_transfer_manager'
            ):
                return self.cancel_transfer(transfer_id, tab_id=tab_id), False
            return self.mark_cancelling(transfer_id, tab_id=tab_id), True

    def mark_cancelling(self, transfer_id: str, *, tab_id: str = '') -> dict | None:
        return self.update_transfer(
            transfer_id,
            tab_id=str(tab_id or '').strip(),
            stage='cancelling',
        )

    def cancel_transfer(self, transfer_id: str, *, tab_id: str = '') -> dict | None:
        return self.update_transfer(
            transfer_id,
            tab_id=str(tab_id or '').strip(),
            state='cancelled',
            stage='cancelled',
            error='',
        )

    def delete_recent_transfer(self, transfer_id: str, *, tab_id: str = '') -> bool:
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return False
        with self._changed:
            item = self._items.get(normalized_id)
            if item and item.get('state') not in self.TERMINAL_STATES:
                raise ValueError('active transfer cannot be deleted; cancel it first')
            removed = (self.batches.delete(normalized_id[6:]) if normalized_id.startswith('batch:')
                       else self.history.delete(normalized_id))
            if removed:
                if normalized_id.startswith('batch:'):
                    batch_id = normalized_id.removeprefix('batch:')
                    for tid, cached in list(self._items.items()):
                        if cached.get('batch_id') == batch_id and cached.get('state') in self.TERMINAL_STATES:
                            self._items.pop(tid, None)
                            if tid in self._recent_ids:
                                self._recent_ids.remove(tid)
                self._items.pop(normalized_id, None)
                if normalized_id in self._recent_ids:
                    self._recent_ids.remove(normalized_id)
                self._changed.notify_all()
            return removed

    def clear_recent_transfers(self, *, tab_id: str = '', machine_id: str = '') -> int:
        with self._changed:
            removed = self.history.clear_recent(machine_id=machine_id)
            if removed:
                # Keep cached terminal transfers from other machines intact.
                for transfer_id, item in list(self._items.items()):
                    if item.get('state') in self.TERMINAL_STATES and self.history.get(transfer_id) is None:
                        self._items.pop(transfer_id, None)
                self._recent_ids = [tid for tid in self._recent_ids if tid in self._items]
                self._changed.notify_all()
            return removed

    def list_transfers(self, tab_id: str = '', *, limit: int = 20, offset: int = 0,
                       machine_id: str = '') -> dict:
        normalized_tab_id = str(tab_id or '').strip()
        machine_id = str(machine_id or '').strip()
        with self._lock:
            active = [self._public_item(item) for item in self._items.values()
                      if item.get('state') == 'running' and not item.get('batch_id') and
                      (not normalized_tab_id or item.get('tab_id') == normalized_tab_id)]
            # Keep browser-tab scoping for live transfers, not durable history.
            active += self.batches.active(normalized_tab_id)
            recent, recent_total = self.history.list_recent(limit=limit, offset=offset, machine_id=machine_id, batch_lookup=self.batches.get)
        active.sort(key=lambda item: item.get('started_at') or '', reverse=True)
        return {'active': active, 'recent': recent, 'recent_total': recent_total,
                'items': active + recent}

    def _apply_patch(self, item: dict, patch: dict):
        previous_bytes = self._normalize_int(item.get('transferred_bytes')) or 0
        previous_mono = float(item.get('_last_progress_mono') or time.monotonic())

        for key in (
            'state', 'stage', 'filename', 'artifact_id', 'error',
            'direction', 'hostname', 'source_path', 'destination_path',
        ):
            if key in patch and patch.get(key) is not None:
                item[key] = str(patch.get(key) or '').strip()

        if 'progress_supported' in patch and patch.get('progress_supported') is not None:
            item['progress_supported'] = bool(patch.get('progress_supported'))

        if 'cancel_supported' in patch and patch.get('cancel_supported') is not None:
            item['cancel_supported'] = bool(patch.get('cancel_supported'))

        if 'total_bytes' in patch:
            item['total_bytes'] = self._normalize_int(patch.get('total_bytes'))

        if 'transferred_bytes' in patch:
            next_bytes = self._normalize_int(patch.get('transferred_bytes'))
            if next_bytes is not None:
                item['transferred_bytes'] = max(0, next_bytes)

        if isinstance(patch.get('metadata'), dict):
            current_metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
            item['metadata'] = {**current_metadata, **patch.get('metadata')}

        now_mono = time.monotonic()
        current_bytes = self._normalize_int(item.get('transferred_bytes')) or 0
        if current_bytes >= previous_bytes:
            elapsed = now_mono - previous_mono
            delta = current_bytes - previous_bytes
            if elapsed > 0.05 and delta > 0:
                instant_speed = delta / elapsed
                previous_ema = float(item.get('_speed_ema') or 0.0)
                speed_ema = instant_speed if previous_ema <= 0 else (0.35 * instant_speed + 0.65 * previous_ema)
                item['_speed_ema'] = speed_ema
                item['speed_bytes_per_sec'] = int(max(0.0, speed_ema))
                item['_last_progress_bytes'] = current_bytes
                item['_last_progress_mono'] = now_mono

        item['updated_at'] = datetime.now().isoformat()

        if item.get('state') in self.TERMINAL_STATES and not item.get('completed_at'):
            item['completed_at'] = item['updated_at']
            item['speed_bytes_per_sec'] = 0
            item['eta_seconds'] = 0 if item.get('state') == 'completed' else None

    def _refresh_derived_fields(self, item: dict):
        total = self._normalize_int(item.get('total_bytes'))
        transferred = self._normalize_int(item.get('transferred_bytes')) or 0

        if total and total > 0:
            transferred = min(max(transferred, 0), total)
            item['transferred_bytes'] = transferred
            item['percent'] = round((transferred / total) * 100.0, 1)
            speed = self._normalize_int(item.get('speed_bytes_per_sec')) or 0
            if speed > 0 and item.get('state') == 'running':
                item['eta_seconds'] = max(0, int((total - transferred) / speed))
            elif item.get('state') == 'running':
                item['eta_seconds'] = None
        else:
            item['percent'] = None
            item['eta_seconds'] = None

        if item.get('state') == 'completed' and total and transferred < total:
            item['transferred_bytes'] = total
            item['percent'] = 100.0

    def _remember_if_terminal(self, item: dict):
        if item.get('state') not in self.TERMINAL_STATES:
            return
        transfer_id = item.get('transfer_id')
        if transfer_id in self._recent_ids:
            self._recent_ids.remove(transfer_id)
        self._recent_ids.insert(0, transfer_id)
        # Bounded *RAM cache* only; the persisted record is never pruned.
        while len(self._recent_ids) > self.MEMORY_RECENT_CACHE_SIZE:
            stale_id = self._recent_ids.pop()
            self._items.pop(stale_id, None)

    def _publish(self, item: dict):
        target_tab_id = str(item.get('tab_id') or '').strip()
        snapshot = self._public_item(item)
        self.event_bus.publish(
            'transfer_updated',
            snapshot,
            target_tab_id=target_tab_id,
        )

    def _publish_lifecycle(self, item: dict, lifecycle: str):
        normalized_lifecycle = str(lifecycle or '').strip().lower()
        if normalized_lifecycle not in {'started', 'stopped', 'error'}:
            return

        target_tab_id = str(item.get('tab_id') or '').strip()
        payload = self._public_item(item)
        payload['lifecycle'] = normalized_lifecycle
        self.event_bus.publish(
            'file_transfer_lifecycle',
            payload,
            target_tab_id=target_tab_id,
        )

    def _public_item(self, item: dict) -> dict:
        return {
            key: value
            for key, value in dict(item or {}).items()
            if not str(key).startswith('_') and key != 'tab_id'
        }

    def _normalize_int(self, value):
        if value is None or value == '':
            return None
        try:
            return max(0, int(value))
        except Exception:
            return None
