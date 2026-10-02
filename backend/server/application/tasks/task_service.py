import threading

from core.protocol.message_types import MSG_TYPE_TRANSFER_CANCEL
from dataclasses import dataclass, field

from server.application.execution.execution_context import TaskExecutionContext
from server.application.tasks.task_types import TASK_TYPE_COMMAND, TASK_TYPE_UPLOAD


@dataclass
class WebExecutionTaskRequest:
    """
    统一 Web 执行请求。

    说明：
    - command / upload 都通过同一条任务创建主链进入
    - runner_name 决定最终交给哪个 task runner 方法
    """

    client_id: str
    command: str
    task_type: str
    runner_name: str
    tab_id: str = ''
    source: str = 'web'
    metadata: dict = field(default_factory=dict)
    use_foreground_guard: bool = True


class WebTaskService:
    """
    Web 任务服务。

    职责：
    - 提交并登记 Web 命令 / 上传任务
    - 占用前台执行槽
    - 启动 runner 真正执行
    - Web upload 使用独立 TransferManager 时不占 foreground；普通 Web command 保持原规则
    """

    def __init__(self, server, task_store, file_service, task_runner, transfer_service=None):
        self.server = server
        self.task_store = task_store
        self.file_service = file_service
        self.task_runner = task_runner
        self.transfer_service = transfer_service
        self.history_orchestrator = self.server.command_history_orchestrator

    def _create_task_with_history(
        self,
        conn,
        request: WebExecutionTaskRequest,
    ):
        entry_id = self.history_orchestrator.begin_execution(
            conn,
            request.command,
            source=request.source,
            should_record=None,
            task_type=request.task_type,
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
                    self.history_orchestrator.discard_execution(conn, entry_id)
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
                self.history_orchestrator.discard_execution(conn, history_entry_id)
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
        self._ensure_active_task(conn, task_id)
        return task, conn

    def _resolve_runner(self, runner_name: str):
        runner = getattr(self.task_runner, runner_name, None)
        if not callable(runner):
            raise ValueError(f'unknown task runner: {runner_name}')
        return runner

    def _submit_request(self, request: WebExecutionTaskRequest):
        conn = self.server.get_target_connection_by_client_id(request.client_id)
        runner = self._resolve_runner(request.runner_name)
        task = self._create_task_with_history(conn, request)
        context = self._build_task_context(conn, task, request)
        acquired = False

        try:
            if request.use_foreground_guard:
                self._acquire_task(context)
                acquired = True
            self._start_task_thread(runner, context)
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
        }

    def submit_web_command(
            self,
            client_id: str,
            command: str,
            tab_id: str = '',
            metadata: dict | None = None,
            source: str = 'web',
    ):
        return self._submit_request(
            WebExecutionTaskRequest(
                client_id=client_id,
                command=command,
                task_type=TASK_TYPE_COMMAND,
                runner_name='run_command_task',
                tab_id=tab_id,
                source=str(source or 'web').strip() or 'web',
                metadata=dict(metadata or {}),
            )
        )

    def cancel_web_task(self, task_id: str):
        try:
            task, conn = self._resolve_cancellable_task(task_id)
        except ValueError:
            task = self.task_store.get_task(task_id)
            transfer = (
                self.transfer_service.find_active_transfer_by_task_id(task_id)
                if self.transfer_service is not None
                else None
            )
            if not task or not transfer:
                raise

            if transfer.get('cancel_supported') is False:
                raise ValueError('current transfer mode does not support cancellation')

            client_id = task.get('client_id') or transfer.get('client_id') or ''
            conn = self.server.get_target_connection_by_client_id(client_id)
            self.task_store.request_cancel(task_id)
            self.transfer_service.mark_cancelling(transfer.get('transfer_id') or '')
            conn.send({
                'type': MSG_TYPE_TRANSFER_CANCEL,
                'transfer_id': transfer.get('transfer_id') or '',
            })
            return {
                'task_id': task_id,
                'client_id': client_id,
                'status': 'cancelling',
                'command_id': None,
                'history_entry_id': task.get('history_entry_id') or '',
                'transfer_id': transfer.get('transfer_id') or '',
            }

        client_id = task.get('client_id') or ''
        cancel_info = self._request_task_cancel(conn, task_id)
        command_id = cancel_info.get('command_id')

        return {
            'task_id': task_id,
            'client_id': client_id,
            'status': 'cancelling',
            'command_id': command_id,
            'history_entry_id': cancel_info.get('history_entry_id') or '',
        }

    def submit_web_upload(
        self,
        client_id: str,
        local_path: str,
        display_name: str,
        remote_path: str = '',
        tab_id: str = '',
        transfer_id: str = '',
    ):
        command = f'upload {display_name}'
        return self._submit_request(
            WebExecutionTaskRequest(
                client_id=client_id,
                command=command,
                task_type=TASK_TYPE_UPLOAD,
                runner_name='run_upload_task',
                tab_id=tab_id,
                source='web',
                metadata={
                    'local_path': local_path,
                    'display_name': display_name,
                    'remote_path': remote_path,
                    'upload_tmp_dir': getattr(self.file_service, 'upload_tmp_dir', ''),
                    'transfer_id': (transfer_id or '').strip(),
                },
                use_foreground_guard=False,
            )
        )
