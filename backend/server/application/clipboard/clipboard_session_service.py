from core.protocol.control import ControlDomain, ClipboardAction
from core.protocol.message_types import MSG_TYPE_CONTROL


class ClipboardSessionService:
    REQUEST_TIMEOUT_SECONDS = 60 * 60

    def __init__(self, server):
        self.server = server

    def get_capabilities(self, client_id: str) -> dict:
        return self._request(client_id, ClipboardAction.GET, {'mode': 'capabilities'})

    def get_clipboard(self, client_id: str) -> dict:
        return self._request(client_id, ClipboardAction.GET, {'mode': 'content'})

    def set_clipboard(self, client_id: str, payload: dict, *, action: str, arguments=None) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('clipboard payload is required')
        return self._request(client_id, ClipboardAction.SET, payload)

    def _request(self, client_id, action, payload):
        client_id = str(client_id or '').strip()
        if not client_id:
            raise ValueError('client_id is required')
        session = self.server.get_target_connection_by_client_id(client_id)
        rows = session.send_command('', type=MSG_TYPE_CONTROL, domain=ControlDomain.CLIPBOARD,
                                    action=action, payload=payload,
                                    extra={'timeout': self.REQUEST_TIMEOUT_SECONDS}, track_execution=False)
        status, result = 0, None
        for status, result in rows:
            pass
        if status != 1:
            if result is None:
                raise ConnectionError('Client disconnected')
            message = result.get('text') if isinstance(result, dict) else result
            if isinstance(result, dict) and result.get('failure_reason') == 'timed_out':
                raise TimeoutError(message or 'Clipboard operation timed out')
            raise RuntimeError(str(message or 'Clipboard operation failed'))
        if not isinstance(result, dict):
            raise RuntimeError('Invalid Clipboard result')
        return result
