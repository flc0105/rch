import json
from dataclasses import dataclass
from core.protocol.result_envelope import ResultStreamState

from server.application.command.command_types import COMMAND_TYPE_COMMAND


@dataclass(frozen=True)
class CollectedCommandResult:
    """A completed request: terminal outcome, visible text and original JSON facts."""
    status: str
    text: str
    data: dict | list | None = None


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

    @staticmethod
    def collect_envelope(result_iter) -> CollectedCommandResult:
        """Collect a request without inferring its final outcome from stream chunks."""
        parts = []
        state = ResultStreamState()
        for item in result_iter:
            state.accept(item)
            displayed = item.visible_text(data_indent=None)
            if displayed:
                parts.append(displayed)
        if state.completion is None:
            raise RuntimeError('Result stream ended without completed event')
        completion = state.completion.event
        data = completion.get('data')
        return CollectedCommandResult(
            status=completion['status'],
            text='\n'.join(part for part in parts if part).strip(),
            data=data if isinstance(data, (dict, list)) else None,
        )

    @staticmethod
    def json_payload(result: CollectedCommandResult, *, command_type=COMMAND_TYPE_COMMAND) -> dict:
        if result.status not in ('success', 'partial'):
            raise RuntimeError(result.text or f'Remote command {result.status}')
        if result.data is not None:
            if not isinstance(result.data, dict):
                raise RuntimeError('Invalid remote JSON payload: expected object')
            return result.data
        # Ordinary text commands may deliberately return JSON text. Typed
        # Control results must provide structured data instead.
        if command_type != COMMAND_TYPE_COMMAND:
            raise RuntimeError('Remote structured command did not return data')
        try:
            payload = json.loads(result.text or '{}')
        except Exception as e:
            raise RuntimeError(f'Invalid remote JSON payload: {e}') from e
        if not isinstance(payload, dict):
            raise RuntimeError('Invalid remote JSON payload: expected object')
        return payload

    # ------------------ read-only completion api ------------------ #
    def stream_completion(self, target, payload: dict, *, timeout: float = 5.0):
        session = self.get_connection(target)
        return session.send_completion(payload, timeout=timeout)

    def run_completion(self, target, payload: dict, *, timeout: float = 5.0) -> dict:
        result = self.collect_envelope(self.stream_completion(target, payload, timeout=timeout))
        if result.status not in ('success', 'partial'):
            raise RuntimeError(result.text or f'Remote completion {result.status}')
        if not isinstance(result.data, dict):
            raise RuntimeError('Invalid completion response: expected data object')
        return result.data

    # ------------------ raw stream api ------------------ #
    def stream_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
        link_foreground_cancel: bool = False,
    ):
        session = self.get_connection(target)
        return session.send_command(
            command,
            type=command_type,
            extra=extra,
            payload=payload,
            domain=domain,
            action=action,
            history_entry_id=history_entry_id,
            **({'link_foreground_cancel': True} if link_foreground_cancel else {}),
        )

    def stream_structured_command(
        self,
        target,
        command: str,
        *,
        command_type: str,
        extra,
        history_entry_id: str = '',
        payload=None,
        domain: str = '',
        action: str = '',
    ):
        return self.stream_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            payload=payload,
            domain=domain,
            action=action,
            history_entry_id=history_entry_id,
        )

    def run_text_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
    ) -> str:
        result = self.collect_envelope(
            self.stream_command(
                target,
                command,
                command_type=command_type,
                extra=extra,
                payload=payload,
                domain=domain, action=action,
                history_entry_id=history_entry_id,
            )
        )

        if result.status not in ('success', 'partial'):
            raise RuntimeError(result.text or 'Remote command failed')

        return result.text

    def run_json_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
    ) -> dict:
        collected = self.collect_envelope(
            self.stream_command(
                target, command, command_type=command_type, extra=extra,
                payload=payload, domain=domain, action=action,
                history_entry_id=history_entry_id,
            )
        )
        return self.json_payload(collected, command_type=command_type)
