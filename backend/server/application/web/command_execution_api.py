from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.tasks.task_service import WebExecutionTaskRequest
from server.application.tasks.task_types import TASK_TYPE_COMMAND
from core.protocol.control import ControlDomain, ConfigurationAction, WatchdogAction


class WebCommandExecutionApi:
    """
    Web 命令执行子外观。

    职责：
    - 提交 Web command
    - 提交 Web upload
    - 取消 Web task
    - 为 CLI 等非路由调用方创建命令执行器
    """

    def __init__(self, task_service, command_executor_factory=None, remote_execution_service=None, *, upload_task_service, task_runner):
        self.task_service = task_service
        self.task_runner = task_runner
        self.upload_task_service = upload_task_service
        self.command_executor_factory = command_executor_factory
        self.remote_execution_service = remote_execution_service

    def _normalize_client_id(self, client_id: str) -> str:
        value = (client_id or '').strip()
        if not value:
            raise ValueError('client_id is required')
        return value

    def _normalize_task_id(self, task_id: str) -> str:
        value = (task_id or '').strip()
        if not value:
            raise ValueError('task_id is required')
        return value

    def _normalize_command(self, command: str) -> str:
        value = (command or '').strip()
        if not value:
            raise ValueError('command is required')
        return value

    def _normalize_upload_payload(self, local_path: str, display_name: str, remote_path: str = '') -> dict:
        normalized_local_path = (local_path or '').strip()
        normalized_display_name = (display_name or '').strip()
        if not normalized_local_path:
            raise ValueError('local_path is required')
        if not normalized_display_name:
            raise ValueError('display_name is required')

        return {
            'local_path': normalized_local_path,
            'display_name': normalized_display_name,
            'remote_path': (remote_path or '').strip(),
        }

    def create_cli_command_executor(
        self,
        session,
        *,
        use_foreground_guard: bool = True,
        foreground_source: str = 'cli',
    ):
        if self.command_executor_factory is None:
            raise RuntimeError('command_executor_factory is not available')
        return self.command_executor_factory.create(
            session,
            use_foreground_guard=use_foreground_guard,
            foreground_source=foreground_source,
        )

    def submit_web_command(
            self,
            client_id: str,
            command: str,
            tab_id: str = '',
            metadata: dict | None = None,
            source: str = 'web',
    ):
        command = self._normalize_command(command)
        return self.task_service.submit(WebExecutionTaskRequest(
            client_id=self._normalize_client_id(client_id), command=command,
            task_type=TASK_TYPE_COMMAND, events=self.task_runner.iter_command_events,
            tab_id=(tab_id or '').strip(), metadata=dict(metadata or {}),
            source=str(source or 'web').strip() or 'web',
            use_foreground_guard=not SERVER_COMMAND_REGISTRY.is_independent_input(command),
        ))

    def submit_web_control(self, client_id: str, command: str, control, *,
                           tab_id: str = '', metadata: dict | None = None):
        from core.protocol.control import execution_policy, ExecutionPolicy
        return self.task_service.submit(WebExecutionTaskRequest(
            client_id=self._normalize_client_id(client_id), command=self._normalize_command(command),
            task_type=TASK_TYPE_COMMAND, events=self.task_runner.iter_control_events,
            tab_id=(tab_id or '').strip(), metadata=dict(metadata or {}), control=control,
            use_foreground_guard=execution_policy(control.domain, control.action) != ExecutionPolicy.INDEPENDENT,
        ))

    def _control(self, client_id, domain, action, payload, *, task_type, source):
        if self.remote_execution_service is None:
            raise RuntimeError('remote_execution_service is not available')
        completion = self.remote_execution_service.run_foreground_control(
            self._normalize_client_id(client_id), domain, action, payload,
            task_type=task_type, source=source,
        )
        if not completion.succeeded:
            raise RuntimeError(completion.event.get('message') or 'Remote control failed')
        return completion.event

    def get_watchdog_status(self, client_id: str):
        result = self._control(client_id, ControlDomain.WATCHDOG, WatchdogAction.STATUS, {},
                               task_type='watchdog_status', source='web_watchdog_status')
        data = result.get('data') if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise RuntimeError('Invalid watchdog status response')
        return data

    def get_runtime_config(self, client_id: str):
        return self._control(client_id, ControlDomain.CONFIGURATION, ConfigurationAction.GET, {},
                             task_type='runtime_config', source='web_runtime_config')

    def update_runtime_config(self, client_id: str, key: str, value):
        return self._control(client_id, ControlDomain.CONFIGURATION, ConfigurationAction.SET,
                             {'key': key, 'value': value}, task_type='runtime_config', source='web_runtime_config')

    def reset_runtime_config(self, client_id: str, key: str):
        return self._control(client_id, ControlDomain.CONFIGURATION, ConfigurationAction.RESET,
                             {'key': key}, task_type='runtime_config', source='web_runtime_config')

    def cancel_web_task(self, task_id: str):
        return self.task_service.cancel_web_task(self._normalize_task_id(task_id))

    def submit_web_upload(
        self,
        client_id: str,
        local_path: str,
        display_name: str,
        remote_path: str = '',
        tab_id: str = '',
        transfer_id: str = '',
        conflict_policy=None,
        operation_id: str = '',
        batch_id: str = '',
    ):
        upload_payload = self._normalize_upload_payload(local_path, display_name, remote_path)
        return self.upload_task_service.submit_upload(
            self._normalize_client_id(client_id), upload_payload['local_path'],
            upload_payload['display_name'], upload_payload['remote_path'],
            tab_id=(tab_id or '').strip(), transfer_id=(transfer_id or '').strip(),
            conflict_policy=conflict_policy, operation_id=operation_id, batch_id=batch_id,
        )
