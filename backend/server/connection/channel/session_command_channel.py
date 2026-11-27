from core.protocol.message_types import MSG_TYPE_COMMAND, MSG_TYPE_CANCEL, MSG_TYPE_ACMD, MSG_TYPE_CONTROL, MSG_TYPE_COMPLETION
from core.protocol.control import build_control_message, execution_policy, ExecutionPolicy
from threading import Lock
import queue
import time

from core.protocol.result_envelope import ResultEvent
from core.utils.timeouts import normalize_positive_timeout



class ClientSessionCommandChannel:
    """
    客户端会话命令通道。

    职责：
    - 生成消息 id
    - 下发远程命令
    - 等待对应结果返回
    """

    def __init__(self, session):
        self.session = session
        self._message_id_counter = 0
        self._id_lock = Lock()

    def generate_message_id(self) -> int:
        with self._id_lock:
            self._message_id_counter += 1
            return self._message_id_counter

    def build_command_payload(self, command: str, command_type: str = MSG_TYPE_COMMAND, extra=None, payload=None, domain='', action='') -> dict:
        command_id = self.generate_message_id()
        if command_type == MSG_TYPE_CONTROL:
            data = build_control_message(command_id, domain, action, payload)
        else:
            if domain or action:
                raise ValueError('Control domain/action requires a control message')
            data = {'type': command_type, 'id': command_id}
            if payload is not None:
                raise ValueError('Structured payload requires a control message type')
            data['text'] = command
        if extra:
            data['extra'] = extra
        return data

    def build_cancel_payload(self, target_command_id: int) -> dict:
        return {
            'type': MSG_TYPE_CANCEL,
            'id': self.generate_message_id(),
            'target_id': target_command_id,
        }

    def send_command(self, command: str, type=MSG_TYPE_COMMAND, extra=None, payload=None, domain='', action='', link_foreground_cancel=False):
        data = self.build_command_payload(command, type, extra, payload, domain, action)

        independent = type == MSG_TYPE_CONTROL and execution_policy(domain, action) == ExecutionPolicy.INDEPENDENT
        timeout = (normalize_positive_timeout((extra or {}).get('timeout')) or 3600) if independent else None
        if independent:
            data['extra'] = {**(extra or {}), 'timeout': timeout}

        bound_task = None

        def dispatch():
            nonlocal bound_task
            bound_task = (None if independent else self.session.runtime.bind_foreground_command_id(data['id']))
            # Register before sending: a fast Client may reply immediately.
            pending = self.session.runtime.pending_results.register(data['id'], request=data)
            if link_foreground_cancel:
                self.session.runtime.bind_foreground_command_id(data['id'])
            try:
                self.session.send(data)
            except Exception:
                if link_foreground_cancel:
                    self.session.runtime.unbind_foreground_command_id(data['id'])
                self.session.runtime.pending_results.remove(data['id'])
                raise
            results = self.wait_for_result(data['id'], command if type == MSG_TYPE_COMMAND else None,
                                           results=pending, timeout=timeout)
            if link_foreground_cancel:
                def linked_results():
                    try:
                        yield from results
                    finally:
                        self.session.runtime.unbind_foreground_command_id(data['id'])
                return linked_results()
            return results

        middleware = self.session.context.command_dispatch
        results = middleware(self.session, data, dispatch) if middleware is not None else dispatch()
        if bound_task and bound_task.get('cancel_requested'):
            self.send_cancel(data['id'])
        return results

    def send_completion(self, payload: dict, *, timeout: float = 5.0):
        """Send a read-only completion request without Foreground or Activity binding."""
        request_id = self.generate_message_id()
        data = {'type': MSG_TYPE_COMPLETION, 'id': request_id}
        data.update(payload if isinstance(payload, dict) else {})
        data['type'] = MSG_TYPE_COMPLETION
        data['id'] = request_id
        pending = self.session.runtime.pending_results.register(request_id)
        try:
            self.session.send(data)
        except Exception:
            self.session.runtime.pending_results.remove(request_id)
            raise

        def _results():
            deadline = time.monotonic() + max(0.1, float(timeout))
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Completion request timed out')
                    try:
                        event = pending.get(timeout=remaining)
                    except queue.Empty:
                        raise TimeoutError('Completion request timed out') from None
                    if event is None:
                        raise ConnectionError('Client disconnected')
                    result = ResultEvent(event)
                    yield result
                    if result.terminal_status is not None:
                        break
            finally:
                self.session.runtime.pending_results.remove(request_id)

        return _results()

    def send_cancel(self, target_command_id: int):
        data = self.build_cancel_payload(target_command_id)
        self.session.send(data)
        return data

    def wait_for_result(self, command_id: int, command: str = '', results=None, timeout=None):
        yield from self.session.runtime.wait_for_result(
            self.session, command_id, command, results=results, timeout=timeout,
        )
