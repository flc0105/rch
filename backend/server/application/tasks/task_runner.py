import logging
import threading
from datetime import datetime

from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.execution.execution_context import TaskExecutionContext
from server.application.tasks.task_status import TaskStreamSummary, WebTaskStatus


class _TaskResultBatch:
    """Merge bursts of task output before the tab-scoped WebSocket queue.

    Each source chunk remains a separate entry, so output boundaries, status and
    JSON formatting are unchanged. Flush under one lock, including completion,
    so a timer can never publish output after command_complete.
    """

    MAX_ITEMS = 128
    MAX_BYTES = 32 * 1024
    MAX_DELAY = 0.03

    def __init__(self, publish):
        self.publish = publish
        self.lock = threading.RLock()
        self.items = []
        self.bytes = 0
        self.timer = None
        self.closed = False

    def add(self, status, text, result=None):
        with self.lock:
            if self.closed:
                raise RuntimeError('Task result batch already closed')
            item = {'status': status, 'text': text}
            if isinstance(result, dict):
                item['result'] = result
            self.items.append(item)
            self.bytes += len(text.encode('utf-8'))
            if len(self.items) >= self.MAX_ITEMS or self.bytes >= self.MAX_BYTES:
                self._flush_locked()
            elif self.timer is None:
                self.timer = threading.Timer(self.MAX_DELAY, self.flush)
                self.timer.daemon = True
                self.timer.start()

    def _flush_locked(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if not self.items:
            return
        items, self.items = self.items, []
        self.bytes = 0
        self.publish(items)

    def flush(self):
        with self.lock:
            self._flush_locked()

    def close(self):
        with self.lock:
            self.closed = True
            self._flush_locked()


class WebTaskRunner:
    """
    Web 任务执行器。

    职责：
    - 消费任务执行事件
    - 推送 SSE
    - 写 history
    - 统一结束收尾
    """

    def __init__(self, server, event_bus, task_store, remote_execution_service, command_executor_factory):
        self.server = server
        self.event_bus = event_bus
        self.task_store = task_store
        self.remote_execution_service = remote_execution_service
        self.command_executor_factory = command_executor_factory
        self.activity_coordinator = self.server.activity_coordinator
        self.logger = logging.getLogger(__name__)
        self.command_execution_pipeline = CommandExecutionPipeline(
            activity_coordinator=self.activity_coordinator,
            error_logger=self.logger,
        )

    def _get_task(self, task_id: str) -> dict:
        return self.task_store.get_task(task_id) or {}

    def _get_runtime_task_context(self, context: TaskExecutionContext) -> dict:
        current = context.session.get_foreground_task() or {}
        if (current.get('task_id') or '').strip() == (context.task_id or '').strip():
            return current
        return {}

    def _get_task_cancel_requested(self, context: TaskExecutionContext) -> bool:
        runtime_task = self._get_runtime_task_context(context)
        if runtime_task:
            if runtime_task.get('cancel_requested'):
                return True

        task = self._get_task(context.task_id)
        return bool(task.get('cancel_requested'))

    def _get_task_tab_id(self, context: TaskExecutionContext) -> str:
        if context.tab_id:
            return context.tab_id

        task = self._get_task(context.task_id)
        return (task.get('tab_id') or '').strip()

    def _get_runtime_command_id(self, context: TaskExecutionContext):
        runtime_task = self._get_runtime_task_context(context)
        if runtime_task.get('command_id') is not None:
            return runtime_task.get('command_id')
        if context.command_id is not None:
            return context.command_id
        return None

    def _finalize_history(self, context: TaskExecutionContext, final_status: str):
        history_entry_id = context.history_entry_id
        self.activity_coordinator.finish(
            context.session,
            history_entry_id,
            final_status == WebTaskStatus.SUCCESS,
            cwd_end=context.session.session_info.cwd,
            status=final_status,
        )

    def _publish_task_result(self, context: TaskExecutionContext, status: int, text: str, result=None):
        target_tab_id = self._get_task_tab_id(context)

        self.event_bus.publish(
            'command_result',
            {
                'task_id': context.task_id,
                'history_entry_id': context.history_entry_id,
                'client_id': context.client_id,
                'command': context.command,
                'command_id': self._get_runtime_command_id(context),
                'status': status,
                'text': text,
                **({'result': result} if isinstance(result, dict) else {}),
                'metadata': dict(context.metadata or {}),
                'time': datetime.now().isoformat(),
            },
            target_tab_id=target_tab_id,
        )

    def _publish_task_result_batch(self, context: TaskExecutionContext, results):
        if len(results) == 1:
            item = results[0]
            self._publish_task_result(context, item['status'], item['text'], item.get('result'))
            return
        self.event_bus.publish(
            'command_result_batch',
            {
                'task_id': context.task_id,
                'history_entry_id': context.history_entry_id,
                'client_id': context.client_id,
                'command': context.command,
                'command_id': self._get_runtime_command_id(context),
                'metadata': dict(context.metadata or {}),
                'results': results,
                'time': datetime.now().isoformat(),
            },
            target_tab_id=self._get_task_tab_id(context),
        )

    def _publish_task_complete(self, context: TaskExecutionContext):
        target_tab_id = self._get_task_tab_id(context)
        task = self._get_task(context.task_id)
        task_status = task.get('status') or WebTaskStatus.ERROR

        self.event_bus.publish(
            'command_complete',
            {
                'task_id': context.task_id,
                'history_entry_id': context.history_entry_id,
                'client_id': context.client_id,
                'command': context.command,
                'command_id': self._get_runtime_command_id(context),
                'success': task_status == WebTaskStatus.SUCCESS,
                'status': task_status,
                'metadata': dict(context.metadata or {}),
                'cancel_requested': self._get_task_cancel_requested(context),
                'cancelled': task_status == WebTaskStatus.CANCELLED,
                'time': datetime.now().isoformat(),
            },
            target_tab_id=target_tab_id,
        )

    def _publish_stream_chunk(self, context: TaskExecutionContext, status: int, text: str, result=None):
        batch = getattr(context, '_result_batch', None)
        if batch is None:
            self._publish_task_result(context, status, text, result)
        else:
            batch.add(status, text, result)

    def _record_stream_chunk(self, context: TaskExecutionContext, status: int, result, summary: TaskStreamSummary,
                             envelope=None):
        text = '' if result is None else str(result)
        self._publish_stream_chunk(context, status, text, envelope)

    def _record_task_event(self, context: TaskExecutionContext, event: CommandExecutionEvent, summary: TaskStreamSummary):
        if event.event_type == CommandExecutionEvent.STARTED:
            envelope = event.payload.get('result_envelope')
            if envelope and envelope.get('type') != 'result':
                self._publish_stream_chunk(context, 1, '', envelope)
            return
        if event.payload.get('result_terminal'):
            summary.terminal_status = event.payload['result_terminal']
            if summary.terminal_status == WebTaskStatus.CANCELLED:
                self.task_store.request_cancel(context.task_id)
            envelope = event.payload.get('result_envelope')
            if event.text or (envelope and envelope.get('type') != 'result'):
                self._publish_stream_chunk(context, event.status, event.text, envelope)
            return
        if event.payload.get('intermediate_result'):
            if event.text:
                self._publish_stream_chunk(context, event.status, event.text, event.payload.get('result_envelope'))
            return

        if event.event_type == CommandExecutionEvent.PROGRESS:
            if event.text:
                self._record_stream_chunk(context, 1, event.text, summary, event.payload.get('result_envelope'))
            return

        if event.event_type == CommandExecutionEvent.CHUNK:
            self._record_stream_chunk(context, event.status, event.text, summary, event.payload.get('result_envelope'))
            return

        if event.event_type == CommandExecutionEvent.ERROR:
            reason = str(event.payload.get('failure_reason') or '')
            summary.mark_dispatch_failure(reason)
            self._record_stream_chunk(context, 0, event.text, summary, event.payload.get('result_envelope'))
            return

        if event.event_type == CommandExecutionEvent.CANCELLED:
            self.task_store.request_cancel(context.task_id)
            summary.mark_cancelled()
            if event.payload.get('terminal'):
                return
            self._record_stream_chunk(context, 0, event.text or 'cancelled', summary, event.payload.get('result_envelope'))
            return

        if event.event_type == CommandExecutionEvent.COMPLETED:
            summary.mark_completed(event.ok)
            return

    def _consume_event_iter(self, context: TaskExecutionContext, event_iter, summary: TaskStreamSummary):
        for event in event_iter:
            self._record_task_event(context, event, summary)

    def _resolve_final_status(self, context: TaskExecutionContext, summary: TaskStreamSummary) -> str:
        return summary.resolve_final_status()

    def _finalize_stream(self, context: TaskExecutionContext, final_status: str, summary: TaskStreamSummary):
        self.task_store.finish_task(
            context.task_id,
            ok=final_status == WebTaskStatus.SUCCESS,
            final_status=final_status,
        )

        try:
            self._finalize_history(context, final_status=final_status)
            self._publish_task_complete(context)
        finally:
            # 终态任务已通过 history/SSE 留痕，不再长期占用内存。
            self.task_store.delete_task(context.task_id)

    def _run_task_events(self, context: TaskExecutionContext, event_iter):
        summary = TaskStreamSummary()
        batch = _TaskResultBatch(lambda results: self._publish_task_result_batch(context, results))
        context._result_batch = batch

        try:
            self._consume_event_iter(context, event_iter, summary)
        except Exception as exc:
            self.logger.exception(
                'WebTaskRunner event stream failed: task_id=%s command=%r task_type=%s',
                context.task_id,
                context.command,
                context.task_type,
            )
            summary.mark_exception(exc)
            self._record_stream_chunk(context, 0, str(exc), summary)
        finally:
            try:
                # All output must be queued before the completion event.
                batch.close()
                final_status = self._resolve_final_status(context, summary)
                self._finalize_stream(context, final_status, summary)
            finally:
                del context._result_batch

    def iter_command_events(self, context: TaskExecutionContext):
        executor = self.command_executor_factory.create(context.session)
        yield from self.command_execution_pipeline.iter_events(
            context,
            executor,
            finalize_history=False,
            swallow_exception=True,
        )

    def iter_control_events(self, context: TaskExecutionContext):
        from core.protocol.message_types import MSG_TYPE_CONTROL

        control = context.control
        if control is None:
            raise ValueError('Control request is required')
        yield CommandExecutionEvent.started(context.command)
        rows = self.remote_execution_service.stream_command(
            context.session, '', command_type=MSG_TYPE_CONTROL,
            domain=control.domain, action=control.action, payload=control.payload,
            history_entry_id=context.history_entry_id,
        )
        yield from CommandExecutionPipeline.iter_result_events(rows)

    def run_task(self, context: TaskExecutionContext, events, release_foreground: bool):
        def event_stream():
            yield from events(context)

        try:
            self._run_task_events(context, event_stream())
        finally:
            if release_foreground:
                context.session.release_foreground_task(task_id=context.task_id, command=context.command)
