import shlex


class WebCommandExecutionApi:
    """
    Web 命令执行子外观。

    职责：
    - 提交 Web command
    - 提交 Web upload
    - 取消 Web task
    - 为 CLI 等非路由调用方创建命令执行器
    """

    def __init__(self, task_service, command_executor_factory=None, remote_execution_service=None):
        self.task_service = task_service
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
        return self.task_service.submit_web_command(
            self._normalize_client_id(client_id),
            self._normalize_command(command),
            tab_id=(tab_id or '').strip(),
            metadata=dict(metadata or {}),
            source=str(source or 'web').strip() or 'web',
        )

    def get_runtime_config(self, client_id: str):
        if self.remote_execution_service is None:
            raise RuntimeError('remote_execution_service is not available')
        return self.remote_execution_service.run_foreground_json_command(
            self._normalize_client_id(client_id),
            'set --json',
            task_type='runtime_config',
            source='web_runtime_config',
        )

    def update_runtime_config(self, client_id: str, key: str, value):
        if self.remote_execution_service is None:
            raise RuntimeError('remote_execution_service is not available')

        normalized_key = str(key or '').strip().upper()
        if not normalized_key:
            raise ValueError('config key is required')

        value_text = self._format_runtime_config_value(value)
        self.remote_execution_service.run_foreground_text_command(
            self._normalize_client_id(client_id),
            f'set {normalized_key} {shlex.quote(value_text)}',
            task_type='runtime_config',
            source='web_runtime_config',
        )
        return self.get_runtime_config(client_id)

    def reset_runtime_config(self, client_id: str, key: str):
        if self.remote_execution_service is None:
            raise RuntimeError('remote_execution_service is not available')

        normalized_key = str(key or '').strip().upper()
        if not normalized_key:
            raise ValueError('config key is required')

        self.remote_execution_service.run_foreground_text_command(
            self._normalize_client_id(client_id),
            f'set --reset {normalized_key}',
            task_type='runtime_config',
            source='web_runtime_config',
        )
        return self.get_runtime_config(client_id)

    def _format_runtime_config_value(self, value) -> str:
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if value is None:
            return 'none'
        return str(value)

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
    ):
        upload_payload = self._normalize_upload_payload(local_path, display_name, remote_path)
        return self.task_service.submit_web_upload(
            self._normalize_client_id(client_id),
            upload_payload['local_path'],
            upload_payload['display_name'],
            upload_payload['remote_path'],
            tab_id=(tab_id or '').strip(),
            transfer_id=(transfer_id or '').strip(),
        )
