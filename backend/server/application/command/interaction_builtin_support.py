"""Convenience API for *opt-in* RCH server builtin command interactions."""


class BuiltinInteractionError(RuntimeError):
    pass


class BuiltinInteractionSupport:
    def __init__(self, server, conn):
        self.server = server
        self.conn = conn

    def _request(self, kind, message, *, title='', timeout=90, placeholder='', options=None, preview=None):
        foreground = self.conn.get_foreground_task() or {}
        task_id = str(foreground.get('task_id') or '').strip()
        client_id = str(getattr(getattr(self.conn, 'session_info', None), 'client_id', '') or '')
        service = self.server.web_service
        task = service.task_store.get_task(task_id) if task_id else None
        if not task or task.get('client_id') != client_id or not task.get('tab_id'):
            raise BuiltinInteractionError('Interactive RCH builtin requires an active Web task')
        return service.interaction_broker.request(
            task_id=task_id, client_id=client_id, tab_id=task['tab_id'],
            kind=kind, message=message, title=title,
            timeout_seconds=timeout, placeholder=placeholder, options=options, preview=preview,
            is_active=lambda: (self.conn.get_foreground_task() or {}).get('task_id') == task_id,
        )

    def confirm(self, message, *, title='Confirmation', timeout=90) -> bool:
        result = self._request('confirm', message, title=title, timeout=timeout)
        return result['status'] == 'answered' and result['value'] is True

    def ask(self, message, *, title='Input required', timeout=90, placeholder='', secret=False) -> str:
        result = self._request('secret' if secret else 'input', message,
                               title=title, timeout=timeout, placeholder=placeholder)
        if result['status'] != 'answered':
            raise BuiltinInteractionError(f'Input not provided ({result["status"]})')
        return result['value']

    def select(self, message, options, *, title='Choose an option', timeout=90) -> str:
        result = self._request('select', message, title=title, timeout=timeout, options=options)
        if result['status'] != 'answered':
            raise BuiltinInteractionError(f'Selection not provided ({result["status"]})')
        return result['value']

    def approve_preview(self, message, preview, *, title='Review execution plan', timeout=90) -> bool:
        """Display structured summary/table/details; approve only on explicit acceptance."""
        result = self._request('preview', message, title=title, timeout=timeout, preview=preview)
        return result['status'] == 'answered' and result['value'] is True


    def select_preview_rows(self, message, preview, *, title='Review execution plan', timeout=90):
        if not isinstance(preview, dict) or not preview.get('row_ids'):
            raise ValueError('Selectable preview requires nonempty row_ids')
        result = self._request('preview', message, title=title, timeout=timeout, preview=preview)
        value = result.get('value')
        if result.get('status') != 'answered' or not isinstance(value, dict):
            raise BuiltinInteractionError('Preview selection rejected, expired, or cancelled')
        selected = value.get('selected_rows')
        if (not isinstance(selected, list) or
                any(not isinstance(key, str) or key not in preview['row_ids'] for key in selected) or
                len(selected) != len(set(selected))):
            raise BuiltinInteractionError('Invalid preview row selection reply')
        return selected
