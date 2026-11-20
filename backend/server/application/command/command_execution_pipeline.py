import logging

from server.application.command.command_execution_event import CommandExecutionEvent
from core.protocol.message_queue import result_terminal_status
from core.utils.command_output import ResultEventType
from server.application.execution.execution_context import ExecutionContext


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
    def build_output_event(status: int, result) -> CommandExecutionEvent:
        """Only event_type controls stream lifecycle; data is never decoded from text."""
        from core.utils.command_output import ResultEventType
        import json
        status = int(status or 0)
        if isinstance(result, dict) and result.get('event_type') in ResultEventType._value2member_map_:
            phase = result['event_type']
            from core.utils.output_marker import render_result_message
            message = render_result_message(result)
            if not message and 'data' in result:
                message = json.dumps(result['data'], ensure_ascii=False, indent=2)
            if phase == ResultEventType.PROGRESS:
                return CommandExecutionEvent.progress(message, payload=result)
            if phase == ResultEventType.STARTED:
                return CommandExecutionEvent.started('', payload=result)
            if phase == ResultEventType.CHUNK:
                return CommandExecutionEvent.chunk(status or 1, message, payload=result)
            # The wire's completed event is terminal. Keep a single final
            # user-facing output, while the Task pipeline owns its own finish.
            return CommandExecutionEvent.chunk(status, message, payload=result)
        if isinstance(result, dict):
            text = str(result.get('text') or result.get('message') or '')
            if result.get('event_type') == CommandExecutionEvent.CANCELLED:
                return CommandExecutionEvent.cancelled(text, payload=result)
            if result.get('event_type') == CommandExecutionEvent.PROGRESS:
                return CommandExecutionEvent.progress(text, payload=result)
            if result.get('event_type') == CommandExecutionEvent.ERROR:
                return CommandExecutionEvent.error(text, payload=result)
            return CommandExecutionEvent.chunk(status, text, payload=result)
        text = '' if result is None else str(result)
        return CommandExecutionEvent.error(text) if status == 0 else CommandExecutionEvent.chunk(status, text)

    @classmethod
    def build_result_event(cls, item):
        status, result = item[:2]
        event = cls.build_output_event(status, result)
        wire = getattr(item, 'event', None)
        envelope = wire
        if envelope is None and isinstance(result, dict) and result.get('event_type') in ResultEventType._value2member_map_:
            envelope = result
        if envelope is not None:
            event.payload = {**event.payload, 'result_envelope': envelope}
        # A wrapped builtin may render its message for the CLI while keeping
        # the complete Result event in item.event. Use that event for terminal
        # status; never infer cancelled/timed_out/partial from the text view.
        terminal_event = (wire if isinstance(wire, dict) and
                          wire.get('event_type') == ResultEventType.COMPLETED else
                          result if isinstance(result, dict) and
                          result.get('event_type') == ResultEventType.COMPLETED else None)
        if terminal_event is not None:
            outcome = terminal_event.get('status', 'error')
            event.payload = {**event.payload, 'result_terminal': outcome}
            if outcome == 'cancelled':
                event = CommandExecutionEvent.cancelled(event.text, payload=event.payload)
            elif outcome not in ('success', 'partial'):
                event = CommandExecutionEvent.error(event.text, payload={**event.payload, 'failure_reason': outcome})
        elif getattr(item, 'terminal_authoritative', False):
            if getattr(item, 'eof', False):
                outcome = result_terminal_status(status, result)
                event.payload = {**event.payload, 'result_terminal': outcome}
                if outcome == 'cancelled':
                    event = CommandExecutionEvent.cancelled(event.text, payload=event.payload)
                elif outcome not in ('success', 'partial'):
                    event = CommandExecutionEvent.error(event.text, payload={**event.payload, 'failure_reason': outcome})
            else:
                event.payload = {**event.payload, 'intermediate_result': True}
        return event

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
        final_status = ""

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
                    event = self.build_result_event(item)

                    if event.payload.get('intermediate_result'):
                        yield event
                        continue
                    if event.payload.get('result_terminal'):
                        final_status = event.payload['result_terminal']
                        final_ok = final_status in ('success', 'partial')
                        cancelled = final_status == 'cancelled'
                        yield event
                        continue
                    if event.event_type == CommandExecutionEvent.ERROR:
                        final_ok = False
                        reason = event.payload.get('failure_reason')
                        if reason in ('timed_out', 'interrupted'):
                            final_status = reason
                    elif event.event_type == CommandExecutionEvent.CANCELLED:
                        cancelled = True
                        final_status = 'cancelled'
                        final_ok = False

                    yield event

        except Exception as exc:
            final_ok = False
            final_status = ('timed_out' if isinstance(exc, TimeoutError) else
                            'interrupted' if isinstance(exc, (ConnectionError, EOFError)) else 'error')
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
                    final_status=final_status,
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