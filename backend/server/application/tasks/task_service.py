import threading

from core.protocol.control import ControlRequest
from dataclasses import dataclass, field

from server.application.execution.execution_context import TaskExecutionContext
from typing import Callable, Iterable
from server.application.command.command_execution_event import CommandExecutionEvent


@dataclass
class WebExecutionTaskRequest:
    """
    统一 Web 执行请求。

    说明：
    - 调用方提供执行事件源及可选的领域取消处理器。
    - metadata 只包含活动关联和前端展示所需信息。
    """

    client_id: str
    command: str
    task_type: str
    events: Callable[[TaskExecutionContext], Iterable[CommandExecutionEvent]]
    tab_id: str = ''
    source: str = 'web'
    metadata: dict = field(default_factory=dict)
    use_foreground_guard: bool = True
    control: ControlRequest | None = None
    cancel_handler: Callable | None = None


class WebTaskService:
    """
    Web 任务服务。

    职责：
    - 提交并登记 Web 执行任务
    - 占用前台执行槽
    - 启动 runner 真正执行
    - 执行槽及取消策略由请求提供，不解析业务命令
    """

    def __init__(self, server, task_store, task_runner):
        self.server = server
        self.task_store = task_store
        self.task_runner = task_runner
        self.activity_coordinator = self.server.activity_coordinator

    def _create_task_with_history(
        self,
        conn,
        request: WebExecutionTaskRequest,
    ):
        entry_id = self.server.command_adapter.prepare_command(
            conn,
            request.command,
            source=request.source,
            should_record=None,
            task_type=request.task_type,
            metadata={key: value for key, value in request.metadata.items() if key != 'operation_id'},
        )

        try:
            task = self.task_store.create_task(
                request.client_id,
                request.command,
                tab_id=request.tab_id,
                session_info=getattr(conn, 'session_info', None),
            )
        except Exception:
            if entry_id:
                try:
                    self.activity_coordinator.discard(conn, entry_id)
                except Exception:
                    # Cleanup must not replace the original task creation failure.
                    pass
            raise

        task['history_entry_id'] = entry_id
        return task

    def _discard_task_setup(self, conn, task: dict):
        task_id = str(task.get('task_id') or '').strip()
        history_entry_id = str(task.get('history_entry_id') or '').strip()
        if task_id:
            self.task_store.delete_task(task_id)
        if history_entry_id:
            try:
                self.activity_coordinator.discard(conn, history_entry_id)
            except Exception:
                # Cleanup must not replace the original submission failure.
                pass

    def _build_task_context(self, conn, task: dict, request: WebExecutionTaskRequest) -> TaskExecutionContext:
        context = TaskExecutionContext.from_task(
            conn,
            task,
            request.command,
            source=request.source,
            task_type=request.task_type,
            metadata=request.metadata,
        )
        context.metadata.update(dict(request.metadata or {}))
        context.control = request.control
        return context

    def _start_task_thread(self, target, *args):
        threading.Thread(
            target=target,
            args=args,
            daemon=True,
        ).start()

    def _acquire_task(self, context: TaskExecutionContext):
        return context.session.acquire_foreground_task(
            task_type=context.task_type,
            command=context.command,
            source=context.source,
            task_id=context.task_id,
            history_entry_id=context.history_entry_id,
            web_task=True,
            tab_id=context.tab_id,
            **({"cancel_policy": context.metadata["cancel_policy"]} if context.metadata.get("cancel_policy") else {}),
        )

    def _ensure_active_task(self, conn, task_id: str):
        foreground_task = conn.get_foreground_task() or {}
        current_task_id = (foreground_task.get('task_id') or '').strip()
        if current_task_id != str(task_id).strip():
            raise ValueError('task is no longer the active foreground task')
        return foreground_task

    def _request_task_cancel(self, conn, task_id: str):
        self.task_store.request_cancel(task_id)
        foreground_task = self._ensure_active_task(conn, task_id)

        cancel_info = conn.request_foreground_task_cancel(task_id=task_id)
        if not cancel_info:
            raise RuntimeError('failed to request task cancellation')

        command_id = cancel_info.get('command_id')
        # During a nested log snapshot this ID targets only that cancellable
        # Control; between snapshots the Server-owned follow stops by flag.
        if command_id:
            conn.send_cancel(command_id)

        result = dict(cancel_info)
        if not result.get('history_entry_id'):
            result['history_entry_id'] = foreground_task.get('history_entry_id') or ''
        return result

    def _resolve_cancellable_task(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if not task:
            raise ValueError('task not found')

        task_status = str(task.get('status') or '').strip()
        if task_status not in ('running', 'cancelling'):
            raise ValueError(f'task is not cancellable: {task_status or "unknown"}')

        client_id = task.get('client_id') or ''
        if not client_id:
            raise ValueError('task client_id is missing')

        conn = self.server.get_target_connection_by_client_id(client_id)
        foreground = self._ensure_active_task(conn, task_id)
        if foreground.get("cancel_policy") == "none":
            raise ValueError("Current execution does not support cancellation")
        return task, conn

    def submit(self, request: WebExecutionTaskRequest):
        conn = self.server.get_target_connection_by_client_id(request.client_id)
        if not callable(request.events):
            raise ValueError('Task event source is required')
        task = self._create_task_with_history(conn, request)
        acquired = False

        try:
            context = self._build_task_context(conn, task, request)
            if request.cancel_handler is not None:
                if not self.task_store.register_cancel_handler(context.task_id, request.cancel_handler):
                    raise RuntimeError("Unable to register task cancellation handler")
            if request.use_foreground_guard:
                self._acquire_task(context)
                acquired = True
            self._start_task_thread(self.task_runner.run_task, context, request.events, acquired)
        except Exception:
            if acquired:
                context.session.release_foreground_task(
                    task_id=context.task_id,
                    command=context.command,
                )
            self._discard_task_setup(conn, task)
            raise

        return {
            'task_id': context.task_id,
            'client_id': request.client_id,
            'command': request.command,
            'history_entry_id': context.history_entry_id,
            **({'operation_id': request.metadata['operation_id']} if request.metadata.get('operation_id') else {}),
        }

    def cancel_web_task(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if not task:
            raise ValueError('task not found')
        if task.get('status') not in ('running', 'cancelling'):
            raise ValueError('task is not cancellable')
        handler = self.task_store.get_cancel_handler(task_id)
        if handler is not None:
            info = handler(task, lambda: self.task_store.request_cancel(task_id))
            return {
                'task_id': task_id,
                'client_id': task['client_id'],
                'status': 'cancelling',
                'command_id': None,
                'history_entry_id': task.get('history_entry_id') or '',
                **info,
            }

        task, conn = self._resolve_cancellable_task(task_id)
        client_id = task.get('client_id') or ''
        cancel_info = self._request_task_cancel(conn, task_id)
        self.activity_coordinator.update_status(
            conn, cancel_info.get('history_entry_id') or '', 'cancelling'
        )
        command_id = cancel_info.get('command_id')

        return {
            'task_id': task_id,
            'client_id': client_id,
            'status': 'cancelling',
            'command_id': command_id,
            'history_entry_id': cancel_info.get('history_entry_id') or '',
        }
