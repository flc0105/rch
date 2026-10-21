import threading
import time
import uuid
from datetime import datetime


class TransferService:
    """
    Server 内存态文件传输状态中心。

    只记录实际传输生命周期，不持久化到 runtime JSON。
    Client -> Server 与 Server -> Client 共用同一份状态模型，并通过 SSE
    定向同步给发起传输的浏览器 tab。
    """

    MAX_RECENT_COMPLETED = 50
    TERMINAL_STATES = {'completed', 'failed', 'cancelled'}

    def __init__(self, event_bus):
        self.event_bus = event_bus
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._items = {}
        self._recent_ids = []
        self.activity_recorder = None

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
    ) -> dict:
        transfer_id = uuid.uuid4().hex
        now_iso = datetime.now().isoformat()
        now_mono = time.monotonic()

        item = {
            'transfer_id': transfer_id,
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
            'progress_supported': True,
            'cancel_supported': True,
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
            self._items[transfer_id] = item
            self._changed.notify_all()

        self._publish(item)
        self._publish_lifecycle(item, 'started')
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
            self._apply_patch(item, patch)
            self._refresh_derived_fields(item)
            self._remember_if_terminal(item)
            snapshot = self._public_item(item)
            next_state = str(item.get('state') or '').strip().lower()
            lifecycle = ''
            if previous_state not in self.TERMINAL_STATES and next_state in self.TERMINAL_STATES:
                lifecycle = 'error' if next_state == 'failed' else 'stopped'
            self._changed.notify_all()

        self._publish(item)
        if lifecycle:
            self._publish_lifecycle(item, lifecycle)
            if self.activity_recorder is not None:
                self.activity_recorder.on_update(snapshot)
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

    def handle_client_update(self, client_id: str, payload: dict):
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
            'error',
            'metadata',
        }
        patch = {key: payload.get(key) for key in allowed if key in payload}
        return self.update_transfer(transfer_id, client_id=client_id, **patch)

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
        active = self.list_active_transfers_for_client(client_id)
        failed = 0
        for item in active:
            transfer_id = item.get('transfer_id') or ''
            updated = self.fail_transfer(
                transfer_id,
                str(error or 'Client disconnected'),
                client_id=str(client_id or '').strip(),
            )
            if updated and updated.get('state') == 'failed':
                failed += 1
        return failed

    def get_transfer(self, transfer_id: str, *, tab_id: str = '') -> dict | None:
        normalized_id = str(transfer_id or '').strip()
        normalized_tab_id = str(tab_id or '').strip()
        if not normalized_id:
            return None

        with self._lock:
            item = self._items.get(normalized_id)
            if not item:
                return None
            if normalized_tab_id and item.get('tab_id') and item.get('tab_id') != normalized_tab_id:
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
                    return None
                if item.get('state') in self.TERMINAL_STATES:
                    return self._public_item(item)

                if deadline is None:
                    self._changed.wait()
                    continue

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._public_item(item)
                self._changed.wait(remaining)

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
        normalized_tab_id = str(tab_id or '').strip()
        if not normalized_id:
            return False

        with self._changed:
            item = self._items.get(normalized_id)
            if not item:
                return False
            if normalized_tab_id and item.get('tab_id') and item.get('tab_id') != normalized_tab_id:
                return False
            if item.get('state') not in self.TERMINAL_STATES:
                raise ValueError('active transfer cannot be deleted; cancel it first')

            self._items.pop(normalized_id, None)
            if normalized_id in self._recent_ids:
                self._recent_ids.remove(normalized_id)
            self._changed.notify_all()
            return True

    def clear_recent_transfers(self, *, tab_id: str = '') -> int:
        normalized_tab_id = str(tab_id or '').strip()
        removed = 0
        with self._changed:
            for transfer_id, item in list(self._items.items()):
                if item.get('state') not in self.TERMINAL_STATES:
                    continue
                if normalized_tab_id and item.get('tab_id') and item.get('tab_id') != normalized_tab_id:
                    continue
                self._items.pop(transfer_id, None)
                if transfer_id in self._recent_ids:
                    self._recent_ids.remove(transfer_id)
                removed += 1
            if removed:
                self._changed.notify_all()
        return removed

    def list_transfers(self, tab_id: str = '') -> dict:
        normalized_tab_id = str(tab_id or '').strip()
        with self._lock:
            items = [
                self._public_item(item)
                for item in self._items.values()
                if not normalized_tab_id or str(item.get('tab_id') or '').strip() == normalized_tab_id
            ]

        items.sort(key=lambda item: item.get('started_at') or '', reverse=True)
        active = [item for item in items if item.get('state') == 'running']
        recent = [item for item in items if item.get('state') != 'running']
        return {
            'active': active,
            'recent': recent[:self.MAX_RECENT_COMPLETED],
            'items': active + recent[:self.MAX_RECENT_COMPLETED],
        }

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

        if item.get('state') in ('completed', 'failed', 'cancelled') and not item.get('completed_at'):
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

        while len(self._recent_ids) > self.MAX_RECENT_COMPLETED:
            stale_id = self._recent_ids.pop()
            stale_item = self._items.get(stale_id)
            if stale_item and stale_item.get('state') != 'running':
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
