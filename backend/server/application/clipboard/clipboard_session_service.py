import threading
import uuid

from core.protocol.message_types import MSG_TYPE_CLIPBOARD_GET, MSG_TYPE_CLIPBOARD_SET


class ClipboardSessionService:
    REQUEST_TIMEOUT_SECONDS = 60 * 60

    def __init__(self, server):
        self.server = server
        self._lock = threading.RLock()
        self._pending = {}

    def get_capabilities(self, client_id: str) -> dict:
        return self._request(
            client_id,
            {'type': MSG_TYPE_CLIPBOARD_GET, 'mode': 'capabilities'},
        )

    def get_clipboard(self, client_id: str) -> dict:
        return self._request(
            client_id,
            {'type': MSG_TYPE_CLIPBOARD_GET, 'mode': 'content'},
        )

    def set_clipboard(self, client_id: str, payload: dict, *, action: str, arguments=None) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('clipboard payload is required')
        return self._request(
            client_id,
            {'type': MSG_TYPE_CLIPBOARD_SET, 'payload': payload},
            operation_action=action, operation_details=arguments or {},
        )

    def handle_client_result(self, client_id: str, data: dict):
        request_id = str(data.get('clipboard_request_id') or '').strip()
        if not request_id:
            return
        with self._lock:
            item = self._pending.get(request_id)
            if not item or item.get('client_id') != str(client_id or '').strip():
                return
            item['result'] = {
                'ok': bool(data.get('ok')),
                'operation': str(data.get('operation') or ''),
                'payload': data.get('payload') if isinstance(data.get('payload'), dict) else {},
                'error': str(data.get('error') or ''),
            }
            item['event'].set()

    def handle_client_disconnected(self, client_id: str):
        normalized = str(client_id or '').strip()
        with self._lock:
            for item in self._pending.values():
                if item.get('client_id') != normalized or item.get('result') is not None:
                    continue
                item['result'] = {
                    'ok': False,
                    'operation': '',
                    'payload': {},
                    'error': 'Client disconnected',
                }
                item['event'].set()

    def _request(self, client_id: str, message: dict, *, operation_action='', operation_details=None) -> dict:
        normalized_client_id = str(client_id or '').strip()
        if not normalized_client_id:
            raise ValueError('client_id is required')

        session = self.server.get_target_connection_by_client_id(normalized_client_id)
        request_id = uuid.uuid4().hex
        event = threading.Event()
        item = {
            'client_id': normalized_client_id,
            'event': event,
            'result': None,
        }
        with self._lock:
            self._pending[request_id] = item

        try:
            session.send({**message, 'clipboard_request_id': request_id})
            if not event.wait(self.REQUEST_TIMEOUT_SECONDS):
                raise TimeoutError('Clipboard operation timed out')
            result = item.get('result') or {}
            if not result.get('ok'):
                raise RuntimeError(result.get('error') or 'Clipboard operation failed')
            return result.get('payload') if isinstance(result.get('payload'), dict) else {}
        except Exception as exc:
            observer = getattr(getattr(session, 'context', None), 'on_client_request_failed', None)
            if callable(observer) and operation_action:
                observer(session, MSG_TYPE_CLIPBOARD_SET, request_id, exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
