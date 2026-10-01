import time

from core.utils.logger import logger
from core.utils.parsing import parse


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

    def __init__(self, server, conn, plan_builder, history_entry_id_provider):
        self.server = server
        self.conn = conn
        self.plan_builder = plan_builder
        self.history_entry_id_provider = history_entry_id_provider

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
            self.server.web_service.device_event_api.ingest(payload)
        except Exception:
            # notify 是附加提醒；提醒失败不能改变被包装命令本身的执行结果。
            logger.error('Failed to emit notify completion event', exc_info=True)

    def notify(self, command: str):
        inner_command = str(command or '').strip()
        if not inner_command:
            yield 0, 'Usage: notify <client-command>'
            return

        started_at = time.monotonic()
        final_ok = True
        terminal = False

        try:
            executor = self._build_inner_executor(inner_command)
            if executor is None:
                final_ok = False
                terminal = True
                yield 0, f'Unable to execute client command: {inner_command}'
                return

            for item in executor():
                status = item[0] if item else 0
                if int(status or 0) == 0:
                    final_ok = False
                yield item

            terminal = True
        except Exception:
            final_ok = False
            terminal = True
            raise
        finally:
            if terminal:
                self._emit_completion_event(
                    status='success' if final_ok else 'failed',
                    duration_ms=self._duration_ms(started_at),
                )
