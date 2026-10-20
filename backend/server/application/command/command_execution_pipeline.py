import logging

from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.execution.execution_context import ExecutionContext


class CommandExecutionPipeline:
    """
    统一命令执行编排入口。

    职责：
    - 调用 command executor
    - 产出标准化执行事件
    - 统一 finalize history
    """

    def __init__(self, command_history_orchestrator, error_logger=None):
        self.command_history_orchestrator = command_history_orchestrator
        self.error_logger = error_logger or logging.getLogger(__name__)

    def _resolve_cwd_end(self, cwd_end_provider=None) -> str:
        cwd_end = ''
        if callable(cwd_end_provider):
            cwd_end = cwd_end_provider() or ''
        return cwd_end

    def _finalize_history(self, context: ExecutionContext, final_ok: bool, cwd_end_provider=None):
        if not context.history_entry_id:
            return

        self.command_history_orchestrator.finalize_execution(
            context.session,
            context.history_entry_id,
            final_ok,
            cwd_end=self._resolve_cwd_end(cwd_end_provider),
        )

    def _build_output_event(self, status: int, result) -> CommandExecutionEvent:
        """
        结果转标准事件。

        约定：
        - 优先支持结构化事件 payload
        - 不再依赖纯文本字符串推断 cancelled
        - 旧的 (status, text) 输出仍兼容
        """
        status = int(status or 0)

        if isinstance(result, dict):
            event_type = str(result.get('event_type') or '').strip().lower()
            text = str(result.get('text') or result.get('message') or '')

            if event_type == CommandExecutionEvent.CANCELLED:
                return CommandExecutionEvent.cancelled(text, payload=result)

            if event_type == CommandExecutionEvent.PROGRESS:
                return CommandExecutionEvent.progress(text, payload=result)

            if event_type == CommandExecutionEvent.ERROR:
                return CommandExecutionEvent.error(text, payload=result)

            if event_type == CommandExecutionEvent.CHUNK:
                return CommandExecutionEvent.chunk(status or 1, text, payload=result)

        text = '' if result is None else str(result)

        if status == 0:
            return CommandExecutionEvent.error(text)

        return CommandExecutionEvent.chunk(status, text)

    def iter_events(
        self,
        context: ExecutionContext,
        command_executor,
        *,
        cwd_end_provider=None,
        finalize_history: bool = True,
        swallow_exception: bool = False,
    ):
        final_ok = True
        cancelled = False

        yield CommandExecutionEvent.started(
            context.command,
            payload={
                'source': context.source,
                'task_id': context.task_id,
                'history_entry_id': context.history_entry_id,
            },
        )

        try:
            func = command_executor.process_command(
                context.command,
                history_entry_id=context.history_entry_id,
            )
            if func:
                for item in func():
                    status = item[0]
                    result = item[1] if len(item) > 1 else ''
                    event = self._build_output_event(status, result)

                    if event.event_type == CommandExecutionEvent.ERROR:
                        final_ok = False
                    elif event.event_type == CommandExecutionEvent.CANCELLED:
                        cancelled = True
                        final_ok = False

                    yield event

        except Exception as exc:
            final_ok = False
            self.error_logger.exception(
                'CommandExecutionPipeline failed: command=%r source=%s task_id=%s history_entry_id=%s',
                context.command,
                context.source,
                context.task_id,
                context.history_entry_id,
            )
            if swallow_exception:
                reason = ('timed_out' if isinstance(exc, TimeoutError) else
                          'interrupted' if isinstance(exc, (ConnectionError, EOFError)) else '')
                yield CommandExecutionEvent.error(str(exc), payload={'failure_reason': reason})
            else:
                raise

        finally:
            if finalize_history:
                self._finalize_history(
                    context,
                    final_ok and not cancelled,
                    cwd_end_provider=cwd_end_provider,
                )

        if cancelled:
            yield CommandExecutionEvent.cancelled(
                'cancelled',
                payload={
                    'terminal': True,
                    'task_id': context.task_id,
                    'history_entry_id': context.history_entry_id,
                },
            )
        else:
            yield CommandExecutionEvent.completed(
                final_ok,
                payload={
                    'task_id': context.task_id,
                    'history_entry_id': context.history_entry_id,
                },
            )