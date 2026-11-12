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
            activity_action=action, activity_arguments=arguments or {},
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

    def _request(self, client_id: str, message: dict, *, activity_action='', activity_arguments=None) -> dict:
        normalized_client_id = str(client_id or '').strip()
        if not normalized_client_id:
            raise ValueError('client_id is required')

        session = self.server.get_target_connection_by_client_id(normalized_client_id)
        history = getattr(self.server, 'command_history_orchestrator', None) if activity_action else None
        activity_id = history.begin_semantic_execution(
            session, 'clipboard', activity_action, activity_arguments or {}, command_type=MSG_TYPE_CLIPBOARD_SET,
        ) if history else ''
        request_id = uuid.uuid4().hex
        event = threading.Event()
        item = {
            'client_id': normalized_client_id,
            'event': event,
            'result': None,
        }
        with self._lock:
            self._pending[request_id] = item

        dispatched = False
        try:
            session.send({**message, 'clipboard_request_id': request_id})
            dispatched = True
            if history and activity_id:
                history.confirm_dispatch(session, activity_id, '', command_type=MSG_TYPE_CLIPBOARD_SET)
            if not event.wait(self.REQUEST_TIMEOUT_SECONDS):
                raise TimeoutError('Clipboard operation timed out')
            result = item.get('result') or {}
            if not result.get('ok'):
                raise RuntimeError(result.get('error') or 'Clipboard operation failed')
            if history and activity_id:
                history.finalize_execution(session, activity_id, True)
            return result.get('payload') if isinstance(result.get('payload'), dict) else {}
        except Exception as exc:
            if history and activity_id:
                if dispatched:
                    status = ('timed_out' if isinstance(exc, TimeoutError) else
                              'interrupted' if str(exc) == 'Client disconnected' else 'error')
                    history.finalize_execution(session, activity_id, False, status=status)
                else:
                    history.discard_activity_intent(activity_id)
            raise
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
