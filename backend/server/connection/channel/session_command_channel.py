from core.protocol.message_types import MSG_TYPE_COMMAND, MSG_TYPE_CANCEL, MSG_TYPE_SCRIPT, MSG_TYPE_ACMD



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

    def generate_message_id(self) -> int:
        self._message_id_counter += 1
        return self._message_id_counter

    def build_command_payload(self, command: str, command_type: str = MSG_TYPE_COMMAND, extra=None) -> dict:
        data = {
            'type': command_type,
            'id': self.generate_message_id(),
            'text': command,
        }
        if extra:
            data['extra'] = extra
        return data

    def build_cancel_payload(self, target_command_id: int) -> dict:
        return {
            'type': MSG_TYPE_CANCEL,
            'id': self.generate_message_id(),
            'target_id': target_command_id,
        }

    def send_command(self, command: str, type=MSG_TYPE_COMMAND, extra=None, history_entry_id: str = ''):
        data = self.build_command_payload(command, type, extra)

        coordinator = getattr(self.session.context, 'activity_coordinator', None)

        adapter = getattr(self.session.context, 'command_dispatch_adapter', None)
        if adapter is not None:
            history_entry_id = history_entry_id or adapter.scoped_entry(self.session)
        bound_task = self.session.runtime.bind_command_execution(
            data.get('id'),
            session=self.session,
            history_entry_id=history_entry_id,
            coordinator=coordinator,
        )
        # Register before sending: a very fast Client (e.g. invalid download)
        # can reply before the caller starts iterating wait_for_result().
        self.session.runtime.pending_command_ids.put(data['id'])
        try:
            self.session.send(data)
        except Exception:
            if self.session.runtime.pending_command_ids.peek_first() == data['id']:
                self.session.runtime.pending_command_ids.get()
            raise
        # Persist only after the transport has accepted an actual Client command.
        # This is deliberately restricted to explicitly prepared Activity intents:
        # internal requests and pure Server builtins never create Activity.
        if adapter is not None:
            adapter.dispatch(self.session, history_entry_id, command, type)

        if bound_task and bound_task.get('cancel_requested'):
            self.send_cancel(data.get('id'))

        results = self.wait_for_result(data.get('id'), command if type == MSG_TYPE_COMMAND else None,
                                       already_registered=True)
        if adapter is not None:
            return adapter.observe_result(self.session, history_entry_id, type, command, results)
        return results

    def send_cancel(self, target_command_id: int):
        data = self.build_cancel_payload(target_command_id)
        self.session.send(data)
        return data

    def wait_for_result(self, command_id: int, command: str = '', already_registered=False):
        yield from self.session.runtime.wait_for_result(
            self.session, command_id, command, already_registered=already_registered,
        )









