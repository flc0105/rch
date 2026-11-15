import json
from dataclasses import dataclass

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
        completion = None
        for item in result_iter:
            event = getattr(item, 'event', None)
            if not isinstance(event, dict):
                value = item[1] if len(item) > 1 else None
                event = value if isinstance(value, dict) and value.get('event_type') else None
            else:
                value = item[1] if len(item) > 1 else None

            if event is not None:
                phase = event.get('event_type')
                if phase == 'completed':
                    if completion is not None:
                        raise RuntimeError('Duplicate completed Result event')
                    completion = event
                if phase == 'started':
                    continue
                # A command may be rendered by the calling domain already;
                # the original data stays separate for machine consumers.
                from core.utils.output_marker import render_result_message
                if phase == 'progress':
                    displayed = render_result_message(event)
                elif isinstance(value, str):
                    displayed = value
                else:
                    displayed = str(event.get('message') or '')
                    if not displayed and 'data' in event:
                        displayed = json.dumps(event['data'], ensure_ascii=False)
                if displayed:
                    parts.append(displayed)
                continue

            # Builtins can still supply local, already-rendered text; only an
            # authoritative completed Result may establish the final status.
            if value is not None:
                parts.append(str(value))

        if completion is None:
            raise RuntimeError('Result stream ended without completed event')
        data = completion.get('data')
        return CollectedCommandResult(
            status=completion['status'],
            text='\n'.join(part for part in parts if part).strip(),
            data=data if isinstance(data, (dict, list)) else None,
        )

    def collect_result(self, result_iter):
        """Text projection for synchronous consumers of a collected Result."""
        result = self.collect_envelope(result_iter)
        return (1 if result.status in ('success', 'partial') else 0), result.text

    @staticmethod
    def json_payload(result: CollectedCommandResult, *, command_type=COMMAND_TYPE_COMMAND) -> dict:
        if result.status not in ('success', 'partial'):
            raise RuntimeError(result.text or f'Remote command {result.status}')
        if result.data is not None:
            if not isinstance(result.data, dict):
                raise RuntimeError('Invalid remote JSON payload: expected object')
            return result.data
        # Text commands deliberately permit JSON text (including XT's deferred
        # pseudo commands). Only that explicit command family uses text JSON.
        if command_type != COMMAND_TYPE_COMMAND:
            raise RuntimeError('Remote structured command did not return data')
        try:
            payload = json.loads(result.text or '{}')
        except Exception as e:
            raise RuntimeError(f'Invalid remote JSON payload: {e}') from e
        if not isinstance(payload, dict):
            raise RuntimeError('Invalid remote JSON payload: expected object')
        return payload

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
        track_execution: bool = True,
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
            **({'track_execution': False} if not track_execution else {}),
        )

    def stream_structured_command(
        self,
        target,
        command: str,
        *,
        command_type: str,
        extra,
        history_entry_id: str = '',
        track_execution: bool = True,
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
            **({'track_execution': False} if not track_execution else {}),
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
        track_execution: bool = True,
    ) -> str:
        status, text = self.collect_result(
            self.stream_command(
                target,
                command,
                command_type=command_type,
                extra=extra,
                payload=payload,
                domain=domain, action=action,
                history_entry_id=history_entry_id,
                **({'track_execution': False} if not track_execution else {}),
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
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
        track_execution: bool = True,
    ) -> dict:
        collected = self.collect_envelope(
            self.stream_command(
                target, command, command_type=command_type, extra=extra,
                payload=payload, domain=domain, action=action,
                history_entry_id=history_entry_id,
                **({'track_execution': False} if not track_execution else {}),
            )
        )
        return self.json_payload(collected, command_type=command_type)
