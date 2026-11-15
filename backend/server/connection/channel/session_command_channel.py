from core.protocol.message_types import MSG_TYPE_COMMAND, MSG_TYPE_CANCEL, MSG_TYPE_ACMD, MSG_TYPE_CONTROL
from core.protocol.control import build_control_message, execution_policy, ExecutionPolicy
from threading import Lock
import logging

logger = logging.getLogger(__name__)
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

    def send_command(self, command: str, type=MSG_TYPE_COMMAND, extra=None, history_entry_id: str = '', payload=None, domain='', action='', link_foreground_cancel=False):
        data = self.build_command_payload(command, type, extra, payload, domain, action)

        independent = type == MSG_TYPE_CONTROL and execution_policy(domain, action) == ExecutionPolicy.INDEPENDENT
        timeout = (normalize_positive_timeout((extra or {}).get('timeout')) or 3600) if independent else None
        if independent:
            data['extra'] = {**(extra or {}), 'timeout': timeout}
        coordinator = getattr(self.session.context, 'activity_coordinator', None)

        # Control Activity eligibility is decided only by the registered Action policy.
        # Command/cancellation binding must not depend on whether Activity is recorded.
        adapter = getattr(self.session.context, 'command_dispatch_adapter', None)
        if adapter is not None:
            try:
                history_entry_id = adapter.prepare_dispatch(self.session, history_entry_id, data)
            except Exception:
                logger.exception("Unable to prepare request Activity")
                history_entry_id = ""
        bound_task = self.session.runtime.bind_command_execution(
            data.get('id'),
            session=self.session,
            history_entry_id=history_entry_id,
            coordinator=coordinator,
            **({'bind_foreground': False} if independent else {}),
        )
        # Register before sending: a very fast Client (e.g. invalid download)
        # can reply before the caller starts iterating wait_for_result().
        pending = self.session.runtime.pending_results.register(data['id'])
        if link_foreground_cancel:
            # This nested Control belongs to a Server-owned foreground generator.
            self.session.runtime.bind_foreground_command_id(data['id'])
        try:
            self.session.send(data)
        except Exception:
            if link_foreground_cancel:
                self.session.runtime.unbind_foreground_command_id(data['id'])
            self.session.runtime.pending_results.remove(data['id'])
            self.session.runtime.clear_history_entry(data['id'])
            if adapter is not None and history_entry_id:
                coordinator.drop(history_entry_id)
            raise
        # Persist only after the transport has accepted an actual Client command.
        # The Activity policy has already been evaluated at the request boundary.
        if adapter is not None:
            history_entry_id = adapter.dispatch(self.session, history_entry_id, data)

        if bound_task and bound_task.get('cancel_requested'):
            self.send_cancel(data.get('id'))

        results = self.wait_for_result(data.get('id'), command if type == MSG_TYPE_COMMAND else None,
                                       results=pending, timeout=timeout, terminal_authoritative=type == MSG_TYPE_CONTROL)
        if adapter is not None:
            results = adapter.observe_result(self.session, history_entry_id, data, results)
        if link_foreground_cancel:
            def linked_results():
                try:
                    yield from results
                finally:
                    self.session.runtime.unbind_foreground_command_id(data['id'])
            return linked_results()
        return results

    def send_cancel(self, target_command_id: int):
        data = self.build_cancel_payload(target_command_id)
        self.session.send(data)
        return data

    def wait_for_result(self, command_id: int, command: str = '', results=None, timeout=None, terminal_authoritative=False):
        yield from self.session.runtime.wait_for_result(
            self.session, command_id, command, results=results, timeout=timeout, terminal_authoritative=terminal_authoritative,
        )
