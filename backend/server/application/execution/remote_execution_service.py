from server.application.command.command_types import COMMAND_TYPE_COMMAND
from server.application.execution.command_stream_service import CommandStreamService
from server.application.execution.foreground_execution_service import ForegroundExecutionService
from server.application.execution.upload_execution_service import UploadExecutionService
from server.application.tasks.task_types import TASK_TYPE_COMMAND


class RemoteExecutionService:
    """
    统一远程执行服务。

    说明：
    - 普通 stream_command / run_text_command / run_json_command：
      不主动占用 foreground task 槽
      适用于已经在上层完成占槽的场景（例如 WebTaskRunner）

    - stream_foreground_command / run_foreground_text_command / run_foreground_json_command：
      在当前方法内部统一占用 foreground task 槽
      适用于前台同步型请求（CLI / remote file / background job 等）

    - upload：
      统一走事件流接口 iter_upload_events，不再保留旧 tuple 流兼容层
    """

    def __init__(self, server, artifact_service=None, transfer_service=None):
        self.server = server
        self.artifact_service = artifact_service
        self.transfer_service = transfer_service

        self.command_stream_service = CommandStreamService(server)
        self.foreground_execution_service = ForegroundExecutionService(
            self.command_stream_service
        )
        self.upload_execution_service = UploadExecutionService(
            server,
            self.command_stream_service,
            artifact_service=self.artifact_service,
            transfer_service=self.transfer_service,
        )

    def get_connection(self, target):
        return self.command_stream_service.get_connection(target)

    def stream_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
        link_foreground_cancel: bool = False,
    ):
        return self.command_stream_service.stream_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            payload=payload,
            domain=domain,
            action=action,
            history_entry_id=history_entry_id,
            **({'link_foreground_cancel': True} if link_foreground_cancel else {}),
        )

    def run_text_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
    ) -> str:
        return self.command_stream_service.run_text_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            payload=payload,
            domain=domain,
            action=action,
            history_entry_id=history_entry_id,
        )

    def run_json_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
    ) -> dict:
        return self.command_stream_service.run_json_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            payload=payload,
            domain=domain,
            action=action,
            history_entry_id=history_entry_id,
        )

    def run_completion(self, target, payload: dict, *, timeout: float = 5.0) -> dict:
        return self.command_stream_service.run_completion(target, payload, timeout=timeout)

    def collect_result(self, result_iter):
        return self.command_stream_service.collect_result(result_iter)

    def stream_foreground_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
        task_type: str = TASK_TYPE_COMMAND,
        source: str = 'foreground',
        task_id: str = '',
        cancel_policy: str = '',
    ):
        return self.foreground_execution_service.stream_foreground_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            payload=payload,
            domain=domain,
            action=action,
            history_entry_id=history_entry_id,
            task_type=task_type,
            source=source,
            task_id=task_id,
            **({'cancel_policy': cancel_policy} if cancel_policy else {}),
        )

    def run_foreground_text_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
        task_type: str = TASK_TYPE_COMMAND,
        source: str = 'foreground',
        task_id: str = '',
    ) -> str:
        return self.foreground_execution_service.run_foreground_text_command(
            target, command, command_type=command_type, extra=extra, payload=payload, domain=domain, action=action,
            history_entry_id=history_entry_id, task_type=task_type, source=source, task_id=task_id,
        )

    def run_foreground_json_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
        task_type: str = TASK_TYPE_COMMAND,
        source: str = 'foreground',
        task_id: str = '',
    ) -> dict:
        return self.foreground_execution_service.run_foreground_json_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            payload=payload,
            domain=domain,
            action=action,
            history_entry_id=history_entry_id,
            task_type=task_type,
            source=source,
            task_id=task_id,
        )

    def run_foreground_control(self, target, domain: str, action: str, payload: dict, *,
                               task_type: str = TASK_TYPE_COMMAND, source: str = 'foreground',
                               foreground: bool = True,
                               history_entry_id: str = ''):
        """Run typed Control under its registered scheduling policy."""
        from core.protocol.message_types import MSG_TYPE_CONTROL
        from core.protocol.control import execution_policy, ExecutionPolicy
        if execution_policy(domain, action) == ExecutionPolicy.INDEPENDENT:
            foreground = False
        status, result = 0, ''
        progress = []
        stream = self.stream_foreground_command if foreground else self.stream_command
        options = {'task_type': task_type, 'source': source} if foreground else {}
        for item in stream(
            target, '', command_type=MSG_TYPE_CONTROL,
            domain=domain, action=action, payload=payload,
            history_entry_id=history_entry_id,
            **options,
        ):
            status, result = item[0], item[1] if len(item) > 1 else ''
            if isinstance(result, str) and result:
                progress.append(result)
        if isinstance(result, dict):
            return status, result
        return status, '\n'.join(progress).strip()

    def open_browser_upload_batch(self, batch_id):
        self.upload_execution_service.open_browser_batch(batch_id)

    def close_browser_upload_batch(self, batch_id):
        self.upload_execution_service.close_browser_batch(batch_id)

    def enqueue_browser_upload(self, batch_id, target, local_path, **options):
        return self.upload_execution_service.enqueue_browser_upload(batch_id, target, local_path, **options)

    def iter_upload_events(
        self,
        target,
        local_path: str,
        *,
        remote_path: str = '',
        display_name: str = '',
        history_entry_id: str = '',
        source: str = 'web',
        task_id: str = '',
        command: str = '',
        tab_id: str = '',
        transfer_id: str = '',
        conflict_policy=None,
        batch_id: str = '',
    ):
        return self.upload_execution_service.iter_upload_operation(
            target,
            local_path,
            batch_id=batch_id,
            remote_path=remote_path,
            display_name=display_name,
            history_entry_id=history_entry_id,
            source=source,
            task_id=task_id,
            command=command,
            tab_id=tab_id,
            transfer_id=transfer_id,
            conflict_policy=conflict_policy,
        )
