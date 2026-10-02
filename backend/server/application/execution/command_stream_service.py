import json

from server.application.command.command_types import COMMAND_TYPE_COMMAND


class CommandStreamService:
    """
    远程命令流服务。

    职责：
    - 解析 target -> session
    - 发送原始远程命令
    - 收集结果流
    - 提供 text/json 两类同步结果读取能力

    说明：
    - 不负责 foreground task 占槽
    - 不负责命令历史编排
    """

    def __init__(self, server):
        self.server = server

    def get_connection(self, target):
        if hasattr(target, 'send_command'):
            return target
        return self.server.get_target_connection_by_client_id(str(target))

    def collect_result(self, result_iter):
        final_status = 1
        parts = []

        for item in result_iter:
            status = item[0]
            text = item[1] if len(item) > 1 else ''
            final_status = status
            if text is not None:
                parts.append(str(text))

        return final_status, '\n'.join(part for part in parts if part).strip()

    # ------------------ raw stream api ------------------ #
    def stream_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        history_entry_id: str = '',
    ):
        session = self.get_connection(target)
        return session.send_command(
            command,
            type=command_type,
            extra=extra,
            history_entry_id=history_entry_id
        )

    def stream_structured_command(
        self,
        target,
        command: str,
        *,
        command_type: str,
        extra,
        history_entry_id: str = '',
    ):
        return self.stream_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            history_entry_id=history_entry_id,
        )

    def run_text_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        history_entry_id: str = '',
    ) -> str:
        status, text = self.collect_result(
            self.stream_command(
                target,
                command,
                command_type=command_type,
                extra=extra,
                history_entry_id=history_entry_id,
            )
        )

        if status != 1:
            raise RuntimeError(text or 'Remote command failed')

        return text

    def run_json_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        history_entry_id: str = '',
    ) -> dict:
        text = self.run_text_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            history_entry_id=history_entry_id,
        )

        try:
            payload = json.loads(text or '{}')
        except Exception as e:
            raise RuntimeError(f'Invalid remote JSON payload: {e}')

        if not isinstance(payload, dict):
            raise RuntimeError('Invalid remote JSON payload: expected object')

        return payload








