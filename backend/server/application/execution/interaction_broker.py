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
            'timeout_seconds', 'placeholder', 'options', 'preview',
        )}

    @staticmethod
    def _normalize_preview(value):
        """Small, plain-text-only presentation schema; never accepts HTML/JS."""
        if not isinstance(value, dict):
            raise ValueError('Preview must be an object')
        if set(value) - {'summary', 'columns', 'rows', 'details', 'notice', 'switches', 'row_ids'}:
            raise ValueError('Unsupported preview field')
        def short(value, limit=500):
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError('Preview text is invalid or too long')
            return value
        result = {'summary': [], 'columns': [], 'rows': [], 'details': [], 'notice': ''}
        summary = value.get('summary', [])
        if not isinstance(summary, list) or len(summary) > 16:
            raise ValueError('Preview summary must be a list of <=16 entries')
        for pair in summary:
            if not isinstance(pair, dict):
                raise ValueError('Invalid preview summary entry')
            result['summary'].append({'label': short(pair.get('label'), 100),
                                      'value': short(pair.get('value'), 1000)})
        if len(result['summary']) > 16:
            raise ValueError('Preview summary exceeds 16 entries')
        columns = value.get('columns', [])
        if not isinstance(columns, list) or len(columns) > 8:
            raise ValueError('Preview columns must be a list of <=8 items')
        for column in columns:
            if not isinstance(column, dict):
                raise ValueError('Invalid preview column')
            key = short(column.get('key'), 40)
            if not key or not key.replace('_', '').isalnum():
                raise ValueError('Preview column key must be alphanumeric')
            result['columns'].append({'key': key, 'label': short(column.get('label'), 100)})
        keys = [col['key'] for col in result['columns']]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate preview columns')
        rows = value.get('rows', [])
        if not isinstance(rows, list) or len(rows) > 100 or (rows and not keys):
            raise ValueError('Preview rows require columns (max 100 rows)')
        for row in rows:
            if not isinstance(row, dict) or set(row) - set(keys):
                raise ValueError('Preview row contains unknown fields')
            result['rows'].append({key: short(row.get(key, ''), 500) for key in keys})
        if 'row_ids' in value:
            row_ids = value['row_ids']
            if (not isinstance(row_ids, list) or not row_ids or
                    len(row_ids) != len(result['rows'])):
                raise ValueError('Preview row_ids must match nonempty preview rows')
            if any(not isinstance(row_id, str) or not 1 <= len(row_id) <= 80 or
                   not row_id.replace('_', '').replace('-', '').isalnum() or
                   not row_id[0].isalnum() for row_id in row_ids):
                raise ValueError('Invalid Preview row ID')
            if len(set(row_ids)) != len(row_ids):
                raise ValueError('Duplicate Preview row IDs')
            result['row_ids'] = list(row_ids)
        details = value.get('details', [])
        if not isinstance(details, list) or len(details) > 16:
            raise ValueError('Preview details must be a list of <=16 items')
        for detail in details:
            if not isinstance(detail, dict):
                raise ValueError('Invalid preview detail')
            result['details'].append({'title': short(detail.get('title'), 120),
                                      'content': short(detail.get('content'), 4000)})
        result['notice'] = short(value.get('notice', ''), 1000)
        if 'switches' in value:
            switches = value['switches']
            if not isinstance(switches, list) or len(switches) > 8:
                raise ValueError('Preview switches must be a list (max 8)')
            result['switches'] = []
            for switch in switches:
                if not isinstance(switch, dict) or set(switch) - {'key', 'label', 'description', 'default'}:
                    raise ValueError('Invalid Preview switch')
                key = short(switch.get('key'), 40)
                if not key or not key.replace('_', '').isalnum():
                    raise ValueError('Invalid Preview switch key')
                default = switch.get('default', False)
                if type(default) is not bool:
                    raise ValueError('Preview switch default must be boolean')
                result['switches'].append({
                    'key': key, 'label': short(switch.get('label'), 160),
                    'description': short(switch.get('description', ''), 500),
                    'default': default,
                })
            ids = [s['key'] for s in result['switches']]
            if len(set(ids)) != len(ids):
                raise ValueError('Duplicate Preview switch keys')
            if 'row_ids' in result and 'selected_rows' in ids:
                raise ValueError('Preview switch key conflicts with row selection')
        return result

    def pending(self, tab_id):
        with self._lock:
            return [self._public(item) for item in self._pending.values()
                    if item['tab_id'] == str(tab_id or '').strip() and not item['event'].is_set()]

    def request(self, *, task_id, client_id, tab_id, kind, message, title='',
                timeout_seconds=90, placeholder='', options=None, preview=None, is_active=None):
        if kind not in ('confirm', 'input', 'secret', 'select', 'preview'):
            raise ValueError('Unsupported interaction kind')
        if not str(task_id or '').strip() or not str(client_id or '').strip():
            raise ValueError('An active task is required for interaction')
        if kind == 'select':
            if not isinstance(options, (list, tuple)) or not (1 <= len(options) <= 24):
                raise ValueError('Select requires 1-24 options')
            if any(not isinstance(option, str) or not option or len(option) > 160 for option in options):
                raise ValueError('Each select option must be a nonempty string (<=160 chars)')
            if len(set(options)) != len(options):
                raise ValueError('Select options must be unique')
            options = list(options)
        else:
            options = []
        preview = self._normalize_preview(preview) if kind == 'preview' else None
        timeout_seconds = max(1, min(int(timeout_seconds), 180))
        item = {
            'interaction_id': uuid.uuid4().hex,
            'task_id': str(task_id), 'client_id': str(client_id),
            'tab_id': str(tab_id or '').strip(), 'kind': kind,
            'title': str(title or '')[:180], 'message': str(message or '')[:3000],
            'placeholder': str(placeholder or '')[:200], 'options': options, 'preview': preview, 'timeout_seconds': timeout_seconds,
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
                if item['kind'] in ('input', 'secret', 'select'):
                    if not isinstance(value, str) or len(value) > 4096:
                        raise ValueError('Input must be a string of at most 4096 characters')
                    if item['kind'] == 'select' and value not in item['options']:
                        raise ValueError('Selected value is not among offered options')
                    item['value'] = value
                elif item['kind'] == 'preview' and item['preview'] and (
                        item['preview'].get('switches') or 'row_ids' in item['preview']):
                    offered = item['preview']
                    switches = offered.get('switches', [])
                    expected = {switch['key'] for switch in switches}
                    if 'row_ids' in offered:
                        if 'selected_rows' in expected:
                            raise ValueError('Preview switch key conflicts with row selection')
                        expected.add('selected_rows')
                    if not isinstance(value, dict) or set(value) != expected:
                        raise ValueError('Preview switch/row reply must provide exactly the offered keys')
                    if any(type(value[switch['key']]) is not bool for switch in switches):
                        raise ValueError('Preview switch values must be boolean')
                    if 'row_ids' in offered:
                        selected = value['selected_rows']
                        allowed = set(offered['row_ids'])
                        if (not isinstance(selected, list) or
                                any(not isinstance(row_id, str) or row_id not in allowed
                                    for row_id in selected) or
                                len(set(selected)) != len(selected)):
                            raise ValueError('Preview selected rows must be unique offered IDs')
                    item['value'] = dict(value)
                else:
                    if item['kind'] == 'preview' and value is not None:
                        raise ValueError('Unexpected Preview response value')
                    item['value'] = True
                item['status'] = 'answered'
            else:
                item['status'] = 'rejected'
                item['value'] = False if item['kind'] in ('confirm', 'preview') else None
            item['event'].set()
            return {'interaction_id': item['interaction_id'], 'status': item['status']}
