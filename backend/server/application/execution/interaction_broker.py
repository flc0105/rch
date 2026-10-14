"""Opt-in, task-bound execution interactions shared by RCH builtins and Script SDK."""
import threading
import time
import uuid


class InteractionBroker:
    def __init__(self, event_bus, task_store):
        self.event_bus = event_bus
        self.task_store = task_store
        self._lock = threading.RLock()
        self._pending = {}

    @staticmethod
    def _public(item):
        return {key: item[key] for key in (
            'interaction_id', 'task_id', 'client_id', 'tab_id', 'kind', 'title', 'message',
            'timeout_seconds', 'placeholder',
        )}

    def pending(self, tab_id):
        with self._lock:
            return [self._public(item) for item in self._pending.values()
                    if item['tab_id'] == str(tab_id or '').strip() and not item['event'].is_set()]

    def request(self, *, task_id, client_id, tab_id, kind, message, title='',
                timeout_seconds=90, placeholder='', is_active=None):
        if kind not in ('confirm', 'input', 'secret'):
            raise ValueError('Unsupported interaction kind')
        if not str(task_id or '').strip() or not str(client_id or '').strip():
            raise ValueError('An active task is required for interaction')
        timeout_seconds = max(1, min(int(timeout_seconds), 180))
        item = {
            'interaction_id': uuid.uuid4().hex,
            'task_id': str(task_id), 'client_id': str(client_id),
            'tab_id': str(tab_id or '').strip(), 'kind': kind,
            'title': str(title or '')[:180], 'message': str(message or '')[:3000],
            'placeholder': str(placeholder or '')[:200], 'timeout_seconds': timeout_seconds,
            'event': threading.Event(), 'status': 'pending', 'value': None,
            'deadline': time.monotonic() + timeout_seconds,
        }
        with self._lock:
            if any(p['task_id'] == item['task_id'] for p in self._pending.values()):
                raise ValueError('Task already has a pending interaction')
            self._pending[item['interaction_id']] = item
        deadline = item['deadline']
        try:
            self.event_bus.publish('interaction_requested', self._public(item), target_tab_id=item['tab_id'])
            while not item['event'].is_set():
                if is_active is not None and not is_active():
                    break
                task = self.task_store.get_task(task_id)
                if not task or task.get('status') not in ('running',):
                    break
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                item['event'].wait(timeout=min(0.25, left))
            with self._lock:
                if item['status'] == 'pending':
                    task_state = self.task_store.get_task(task_id)
                    item['status'] = 'cancelled' if (not task_state or task_state.get('status') != 'running') else 'expired'
                return {'status': item['status'], 'value': item['value']}
        finally:
            with self._lock:
                self._pending.pop(item['interaction_id'], None)
            self.event_bus.publish('interaction_resolved', {
                'interaction_id': item['interaction_id'], 'task_id': task_id,
                'status': item['status'],
            }, target_tab_id=item['tab_id'])

    def answer(self, interaction_id, *, approved=False, value=None):
        with self._lock:
            item = self._pending.get(str(interaction_id or '').strip())
            if item is None or item['status'] != 'pending' or item['event'].is_set():
                raise ValueError('Interaction not pending or already answered')
            if time.monotonic() >= item.get('deadline', 0):
                raise ValueError('Interaction approval deadline has passed')
            task = self.task_store.get_task(item['task_id'])
            if not task or task.get('status') != 'running':
                raise ValueError('Interaction task is no longer running')
            if approved:
                if item['kind'] in ('input', 'secret'):
                    if not isinstance(value, str) or len(value) > 4096:
                        raise ValueError('Input must be a string of at most 4096 characters')
                    item['value'] = value
                else:
                    item['value'] = True
                item['status'] = 'answered'
            else:
                item['status'] = 'rejected'
                item['value'] = False if item['kind'] == 'confirm' else None
            item['event'].set()
            return {'interaction_id': item['interaction_id'], 'status': item['status']}
