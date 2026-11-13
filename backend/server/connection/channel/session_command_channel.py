from core.protocol.message_types import MSG_TYPE_COMMAND, MSG_TYPE_CANCEL, MSG_TYPE_ACMD, MSG_TYPE_CONTROL
from core.protocol.control import build_control_message, execution_policy, ExecutionPolicy
from threading import Lock
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

    def send_command(self, command: str, type=MSG_TYPE_COMMAND, extra=None, history_entry_id: str = '', payload=None, domain='', action='', track_execution=True):
        data = self.build_command_payload(command, type, extra, payload, domain, action)

        independent = type == MSG_TYPE_CONTROL and execution_policy(domain, action) == ExecutionPolicy.INDEPENDENT
        timeout = (normalize_positive_timeout((extra or {}).get('timeout')) or 3600) if independent else None
        if independent:
            data['extra'] = {**(extra or {}), 'timeout': timeout}
        coordinator = getattr(self.session.context, 'activity_coordinator', None)

        adapter = getattr(self.session.context, 'command_dispatch_adapter', None)
        if not track_execution:
            adapter = None
        if adapter is not None:
            history_entry_id = history_entry_id or adapter.scoped_entry(self.session)
        bound_task = self.session.runtime.bind_command_execution(
            data.get('id'),
            session=self.session,
            history_entry_id=history_entry_id,
            coordinator=coordinator,
            **({'bind_foreground': False} if independent else {}),
        ) if track_execution else None
        # Register before sending: a very fast Client (e.g. invalid download)
        # can reply before the caller starts iterating wait_for_result().
        pending = self.session.runtime.pending_results.register(data['id'])
        try:
            self.session.send(data)
        except Exception:
            self.session.runtime.pending_results.remove(data['id'])
            raise
        # Persist only after the transport has accepted an actual Client command.
        # This is deliberately restricted to explicitly prepared Activity intents:
        # internal requests and pure Server builtins never create Activity.
        if adapter is not None:
            adapter.dispatch(self.session, history_entry_id, command, type, payload=payload, domain=domain, action=action)

        if bound_task and bound_task.get('cancel_requested'):
            self.send_cancel(data.get('id'))

        results = self.wait_for_result(data.get('id'), command if type == MSG_TYPE_COMMAND else None,
                                       results=pending, timeout=timeout)
        if adapter is not None:
            return adapter.observe_result(self.session, history_entry_id, type, command, results, payload=payload, domain=domain, action=action)
        return results

    def send_cancel(self, target_command_id: int):
        data = self.build_cancel_payload(target_command_id)
        self.session.send(data)
        return data

    def wait_for_result(self, command_id: int, command: str = '', results=None, timeout=None):
        try:
            yield from self.session.runtime.wait_for_result(
                self.session, command_id, command, results=results, timeout=timeout,
            )
        except Exception as exc:
            observer = getattr(self.session.context, 'on_client_request_failed', None)
            if callable(observer):
                try:
                    observer(self.session, MSG_TYPE_CONTROL, command_id, exc)
                except Exception:
                    pass
            raise









