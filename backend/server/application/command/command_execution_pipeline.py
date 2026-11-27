import logging

from server.application.command.command_execution_event import CommandExecutionEvent
from core.protocol.result_envelope import ResultEvent
from core.utils.command_output import ResultEventType
from server.application.execution.execution_context import ExecutionContext
from server.application.command.wrapped_result import iter_inner_results


class CommandExecutionPipeline:
    """
    统一命令执行编排入口。

    职责：
    - 调用 command executor
    - 产出标准化执行事件
    - 统一 finalize history
    """

    def __init__(self, activity_coordinator, error_logger=None):
        self.activity_coordinator = activity_coordinator
        self.error_logger = error_logger or logging.getLogger(__name__)

    def _resolve_cwd_end(self, cwd_end_provider=None) -> str:
        cwd_end = ''
        if callable(cwd_end_provider):
            cwd_end = cwd_end_provider() or ''
        return cwd_end

    def _finalize_history(self, context: ExecutionContext, final_ok: bool, cwd_end_provider=None, final_status=""):
        if not context.history_entry_id:
            return

        self.activity_coordinator.finish(
            context.session,
            context.history_entry_id,
            final_ok,
            cwd_end=self._resolve_cwd_end(cwd_end_provider),
            **({'status': final_status} if final_status else {}),
        )

    @staticmethod
    def build_result_event(item: ResultEvent) -> CommandExecutionEvent:
        envelope = item.event
        phase = item.phase
        payload = {**envelope, 'result_envelope': envelope}
        if phase == ResultEventType.STARTED:
            return CommandExecutionEvent.started('', payload=payload)
        text = item.visible_text()
        outcome = item.terminal_status
        if outcome is None:
            payload['intermediate_result'] = True
            if phase == ResultEventType.PROGRESS:
                return CommandExecutionEvent.progress(text, payload=payload)
            return CommandExecutionEvent.chunk(1, text, payload=payload)
        payload['result_terminal'] = outcome
        if outcome == 'cancelled':
            return CommandExecutionEvent.cancelled(text, payload=payload)
        if not item.succeeded:
            return CommandExecutionEvent.error(text, payload={**payload, 'failure_reason': outcome})
        return CommandExecutionEvent.chunk(1, text, payload=payload)

    @staticmethod
    def iter_result_events(items):
        """Emit intermediate events immediately and exactly one terminal outcome."""
        for item in iter_inner_results(items):
            yield CommandExecutionPipeline.build_result_event(item)

    def iter_events(
        self,
        context: ExecutionContext,
        command_executor,
        *,
        cwd_end_provider=None,
        finalize_history: bool = True,
        swallow_exception: bool = False,
    ):
        final_status = 'interrupted'

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
            for event in self.iter_result_events(func() if func else ()):
                if event.payload.get('result_terminal'):
                    final_status = event.payload['result_terminal']
                yield event

        except Exception as exc:
            final_status = ('timed_out' if isinstance(exc, TimeoutError) else
                            'interrupted' if isinstance(exc, (ConnectionError, EOFError)) else 'error')
            self.error_logger.exception(
                'CommandExecutionPipeline failed: command=%r source=%s task_id=%s history_entry_id=%s',
                context.command, context.source, context.task_id, context.history_entry_id,
            )
            if swallow_exception:
                yield self.build_result_event(ResultEvent.completed(final_status, str(exc)))
            else:
                raise

        finally:
            if finalize_history:
                self._finalize_history(
                    context,
                    final_status in ('success', 'partial'),
                    cwd_end_provider=cwd_end_provider,
                    final_status=final_status,
                )

        if final_status == 'cancelled':
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
                final_status in ('success', 'partial'),
                payload={
                    'task_id': context.task_id,
                    'history_entry_id': context.history_entry_id,
                },
            )