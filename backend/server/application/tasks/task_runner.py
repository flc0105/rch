import logging
import os
import shutil
from datetime import datetime

from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.execution.execution_context import TaskExecutionContext
from server.application.tasks.task_status import TaskStreamSummary, WebTaskStatus


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
        self.history_orchestrator = self.server.command_history_orchestrator
        self.logger = logging.getLogger(__name__)
        self.command_execution_pipeline = CommandExecutionPipeline(
            command_history_orchestrator=self.history_orchestrator,
            error_logger=self.logger,
        )

    def _get_task(self, task_id: str) -> dict:
        return self.task_store.get_task(task_id) or {}

    def _get_runtime_task_context(self, context: TaskExecutionContext) -> dict:
        current = context.session.get_foreground_task() or {}
        if (current.get('task_id') or '').strip() == (context.task_id or '').strip():
            return current
        return {}

    def _get_history_entry_id(self, context: TaskExecutionContext) -> str:
        runtime_task = self._get_runtime_task_context(context)
        if runtime_task.get('history_entry_id'):
            return runtime_task.get('history_entry_id') or ''

        if context.history_entry_id:
            return context.history_entry_id

        task = self._get_task(context.task_id)
        return task.get('history_entry_id') or ''

    def _get_task_cancel_requested(self, context: TaskExecutionContext) -> bool:
        runtime_task = self._get_runtime_task_context(context)
        if runtime_task:
            return bool(runtime_task.get('cancel_requested'))

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

    def _append_history_output(self, context: TaskExecutionContext, status: int, text: str):
        history_entry_id = self._get_history_entry_id(context)
        self.history_orchestrator.append_output(
            context.session,
            history_entry_id,
            status,
            text,
            0,
        )

    def _finalize_history(self, context: TaskExecutionContext, final_status: str):
        history_entry_id = self._get_history_entry_id(context)
        self.history_orchestrator.finalize_execution(
            context.session,
            history_entry_id,
            final_status == WebTaskStatus.SUCCESS,
            cwd_end=context.session.session_info.cwd,
        )

    def _publish_task_result(self, context: TaskExecutionContext, status: int, text: str):
        target_tab_id = self._get_task_tab_id(context)

        self.event_bus.publish(
            'command_result',
            {
                'task_id': context.task_id,
                'client_id': context.client_id,
                'command': context.command,
                'command_id': self._get_runtime_command_id(context),
                'status': status,
                'text': text,
                'metadata': dict(context.metadata or {}),
                'time': datetime.now().isoformat(),
            },
            target_tab_id=target_tab_id,
        )

    def _publish_task_complete(self, context: TaskExecutionContext):
        target_tab_id = self._get_task_tab_id(context)
        task = self._get_task(context.task_id)
        task_status = task.get('status') or WebTaskStatus.ERROR

        self.event_bus.publish(
            'command_complete',
            {
                'task_id': context.task_id,
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

    def _publish_stream_chunk(self, context: TaskExecutionContext, status: int, text: str):
        self._publish_task_result(context, status, text)
        self._append_history_output(context, status, text)

    def _record_stream_chunk(self, context: TaskExecutionContext, status: int, result, summary: TaskStreamSummary):
        text = '' if result is None else str(result)
        self._publish_stream_chunk(context, status, text)
        summary.record_chunk(status, text)

    def _record_task_event(self, context: TaskExecutionContext, event: CommandExecutionEvent, summary: TaskStreamSummary):
        if event.event_type == CommandExecutionEvent.STARTED:
            return

        if event.event_type == CommandExecutionEvent.PROGRESS:
            if event.text:
                self._record_stream_chunk(context, 1, event.text, summary)
            return

        if event.event_type == CommandExecutionEvent.CHUNK:
            self._record_stream_chunk(context, event.status, event.text, summary)
            return

        if event.event_type == CommandExecutionEvent.ERROR:
            self._record_stream_chunk(context, 0, event.text, summary)
            return

        if event.event_type == CommandExecutionEvent.CANCELLED:
            self.task_store.request_cancel(context.task_id)
            if event.payload.get('terminal'):
                return
            self._record_stream_chunk(context, 0, event.text or 'cancelled', summary)
            return

        if event.event_type == CommandExecutionEvent.COMPLETED:
            return

    def _consume_event_iter(self, context: TaskExecutionContext, event_iter, summary: TaskStreamSummary):
        for event in event_iter:
            self._record_task_event(context, event, summary)

    def _resolve_final_status(self, context: TaskExecutionContext, summary: TaskStreamSummary) -> str:
        return summary.resolve_final_status(
            cancel_requested=self._get_task_cancel_requested(context)
        )

    def _finalize_stream(self, context: TaskExecutionContext, final_status: str, summary: TaskStreamSummary):
        self.task_store.finish_task(
            context.task_id,
            ok=summary.is_success(),
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

        try:
            self._consume_event_iter(context, event_iter, summary)
        except Exception as exc:
            self.logger.exception(
                'WebTaskRunner event stream failed: task_id=%s command=%r task_type=%s',
                context.task_id,
                context.command,
                context.task_type,
            )
            summary.mark_exception()
            self._record_stream_chunk(context, 0, str(exc), summary)
        finally:
            final_status = self._resolve_final_status(context, summary)
            self._finalize_stream(context, final_status, summary)

    def _iter_command_events(self, context: TaskExecutionContext):
        context.history_entry_id = self._get_history_entry_id(context)
        executor = self.command_executor_factory.create(context.session)
        yield from self.command_execution_pipeline.iter_events(
            context,
            executor,
            finalize_history=False,
            swallow_exception=True,
        )

    def _iter_upload_events(self, context: TaskExecutionContext):
        context.history_entry_id = self._get_history_entry_id(context)
        yield from self.remote_execution_service.iter_upload_events(
            context.session,
            context.metadata.get('local_path') or '',
            remote_path=context.metadata.get('remote_path') or '',
            history_entry_id=context.history_entry_id,
            source=context.source,
            task_id=context.task_id,
            command=context.command,
            tab_id=self._get_task_tab_id(context),
            transfer_id=context.metadata.get('transfer_id') or '',
            use_transfer_manager=True,
        )

    def _release_task(self, context: TaskExecutionContext) -> None:
        context.session.release_foreground_task(task_id=context.task_id, command=context.command)

    # def _cleanup_upload_local_temp(self, context: TaskExecutionContext):
    #     local_path = context.metadata.get('local_path') or ''
    #     upload_tmp_dir = context.metadata.get('upload_tmp_dir') or ''
    #
    #     try:
    #         if os.path.exists(local_path):
    #             os.remove(local_path)
    #         parent_dir = os.path.dirname(local_path)
    #         if upload_tmp_dir and parent_dir.startswith(upload_tmp_dir) and os.path.isdir(parent_dir):
    #             shutil.rmtree(parent_dir, ignore_errors=True)
    #     except Exception:
    #         pass

    def _is_under_directory(self, path: str, directory: str) -> bool:
        if not path or not directory:
            return False

        try:
            abs_path = os.path.abspath(path)
            abs_dir = os.path.abspath(directory)
            return os.path.commonpath([abs_path, abs_dir]) == abs_dir
        except Exception:
            return False

    def _cleanup_upload_local_temp(self, context: TaskExecutionContext):
        local_path = context.metadata.get('local_path') or ''
        upload_tmp_dir = context.metadata.get('upload_tmp_dir') or ''

        # 只清理浏览器上传暂存区，避免误删 shared_files 等永久文件。
        if not self._is_under_directory(local_path, upload_tmp_dir):
            return

        try:
            if os.path.exists(local_path):
                os.remove(local_path)
            parent_dir = os.path.dirname(local_path)
            if self._is_under_directory(parent_dir, upload_tmp_dir) and os.path.isdir(parent_dir):
                shutil.rmtree(parent_dir, ignore_errors=True)
        except Exception:
            pass

    def run_command_task(self, context: TaskExecutionContext):
        try:
            self._run_task_events(context, self._iter_command_events(context))
        finally:
            self._release_task(context)

    def run_upload_task(self, context: TaskExecutionContext):
        try:
            self._run_task_events(context, self._iter_upload_events(context))
        finally:
            # Web upload 已迁到 Client TransferManager，不占 foreground task。
            self._cleanup_upload_local_temp(context)