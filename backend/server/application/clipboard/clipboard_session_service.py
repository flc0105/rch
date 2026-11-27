from core.protocol.control import ControlDomain, ClipboardAction
from core.protocol.message_types import MSG_TYPE_CONTROL


class ClipboardSessionService:
    REQUEST_TIMEOUT_SECONDS = 60 * 60

    def __init__(self, server):
        self.server = server

    def get_capabilities(self, client_id: str) -> dict:
        return self._request(client_id, ClipboardAction.GET, {'mode': 'capabilities'})

    def get_clipboard(self, client_id: str, *, tab_id='') -> dict:
        return self._request(client_id, ClipboardAction.GET, {'mode': 'content'}, tab_id=tab_id)

    def set_clipboard(self, client_id: str, payload: dict, *, action: str, arguments=None, tab_id='') -> dict:
        if not isinstance(payload, dict):
            raise ValueError('clipboard payload is required')
        return self._request(client_id, ClipboardAction.SET, payload, tab_id=tab_id)

    def _request(self, client_id, action, payload, *, tab_id=''):
        client_id = str(client_id or '').strip()
        if not client_id:
            raise ValueError('client_id is required')
        session = self.server.get_target_connection_by_client_id(client_id)
        rows = session.send_command('', type=MSG_TYPE_CONTROL, domain=ControlDomain.CLIPBOARD,
                                    action=action, payload=payload,
                                    extra={'timeout': self.REQUEST_TIMEOUT_SECONDS, 'tab_id': tab_id})
        from core.protocol.result_envelope import ResultStreamState
        state = ResultStreamState()
        for item in rows:
            state.accept(item)
        if state.completion is None:
            raise ConnectionError('Client disconnected')
        result = state.completion.event
        if not state.completion.succeeded:
            message = result.get('message') or ''
            if state.terminal_status == 'timed_out':
                raise TimeoutError(message or 'Clipboard operation timed out')
            if state.terminal_status == 'interrupted':
                raise ConnectionError(message or 'Client disconnected')
            raise RuntimeError(str(message or 'Clipboard operation failed'))
        if action == ClipboardAction.SET:
            return {'message': str(result.get('message') or '')} if isinstance(result, dict) else {}
        data = result.get('data') if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise RuntimeError('Invalid Clipboard result')
        return data
