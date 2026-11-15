import time

from core.utils.logger import logger
from core.utils.parsing import parse
from core.protocol.result_envelope import ResultEnvelope
from core.protocol.message_queue import ResultChunk
from .wrapped_result import inner_result_event, inner_terminal_status


class CommandNotifyBuiltinSupport:
    """
    notify 内建命令支持。

    语义：
    - notify <client-command>
    - 内部命令走现有 client command 规划/执行链路
    - 内部输出保持原样返回
    - 内部命令结束后通过现有 Device Event 管线发出完成事件
    """

    EVENT_KIND = 'command.notify.finished'

    def __init__(self, conn, plan_builder, history_entry_id_provider, device_event_service):
        self.conn = conn
        self.plan_builder = plan_builder
        self.history_entry_id_provider = history_entry_id_provider
        self.device_event_service = device_event_service

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return max(0, int((time.monotonic() - started_at) * 1000))

    @staticmethod
    def _format_duration(duration_ms: int) -> str:
        return f'{max(0, int(duration_ms or 0)) / 1000:.1f}s'

    def _get_session_info(self):
        return getattr(self.conn, 'session_info', None)

    def _build_inner_executor(self, command: str):
        name, arg = parse(command)
        return self.plan_builder.resolve(command, name, arg)

    def _emit_completion_event(self, *, status: str, duration_ms: int):
        session_info = self._get_session_info()
        client_id = str(getattr(session_info, 'client_id', '') or '').strip()
        if not client_id:
            return

        normalized_status = 'success' if status == 'success' else 'failed'
        message = f'{normalized_status.capitalize()} · {self._format_duration(duration_ms)}'
        history_entry_id = str(self.history_entry_id_provider() or '').strip()

        payload = {
            'client_id': client_id,
            'hostname': str(getattr(session_info, 'hostname', '') or '').strip(),
            'kind': self.EVENT_KIND,
            'source': {
                'type': 'server_builtin',
                'id': history_entry_id,
                'name': 'notify',
            },
            'data': {
                'status': normalized_status,
                'duration_ms': int(duration_ms),
                'history_entry_id': history_entry_id,
            },
            'message': message,
        }

        try:
            self.device_event_service.ingest(payload)
        except Exception:
            # notify 是附加提醒；提醒失败不能改变被包装命令本身的执行结果。
            logger.error('Failed to emit notify completion event', exc_info=True)

    def notify(self, command: str):
        inner_command = str(command or '').strip()
        if not inner_command:
            message = 'Usage: notify <client-command>'
            envelope = ResultEnvelope(status='error', message=message).as_payload()
            yield ResultChunk(0, message, True, terminal_authoritative=True, event=envelope)
            return

        started_at = time.monotonic()
        final_outcome = 'interrupted'
        terminal = False
        saw_protocol_events = False
        fallback_status = None

        try:
            executor = self._build_inner_executor(inner_command)
            if executor is None:
                final_outcome = 'error'
                terminal = True
                message = f'Unable to execute client command: {inner_command}'
                envelope = ResultEnvelope(status='error', message=message).as_payload()
                yield ResultChunk(0, message, True, terminal_authoritative=True, event=envelope)
                return

            for item in executor():
                event = inner_result_event(item)
                saw_protocol_events |= event is not None
                outcome = inner_terminal_status(item)
                if outcome is not None:
                    final_outcome = outcome
                    terminal = True
                elif event is None and not hasattr(item, 'eof'):
                    fallback_status = int(item[0] or 0)
                yield item
            if not terminal and not saw_protocol_events and fallback_status is not None:
                final_outcome = 'success' if fallback_status == 1 else 'error'
            terminal = True
        except Exception:
            final_outcome = 'error'
            terminal = True
            raise
        finally:
            if terminal:
                self._emit_completion_event(
                    status='success' if final_outcome in ('success', 'partial') else 'failed',
                    duration_ms=self._duration_ms(started_at),
                )
