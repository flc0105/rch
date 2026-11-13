from core.protocol.structured_arg_codec import encode_structured_arg
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

    HTTP_RECEIVE_COMMAND_NAME = 'receive_file'

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

    def _build_http_receive_command(self, payload: dict) -> str:
        return f'{self.HTTP_RECEIVE_COMMAND_NAME} {encode_structured_arg(payload)}'

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
                               task_type: str = TASK_TYPE_COMMAND, source: str = 'foreground'):
        """Run a one-shot typed Control while retaining the foreground task lifecycle."""
        from core.protocol.message_types import MSG_TYPE_CONTROL
        status, result = 0, ''
        progress = []
        for item in self.stream_foreground_command(
            target, '', command_type=MSG_TYPE_CONTROL,
            domain=domain, action=action, payload=payload,
            task_type=task_type, source=source,
        ):
            status, result = item[0], item[1] if len(item) > 1 else ''
            if isinstance(result, str) and result:
                progress.append(result)
        if isinstance(result, dict):
            return status, result
        return status, '\n'.join(progress).strip()

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
        use_transfer_manager: bool = False,
    ):
        return self.upload_execution_service.iter_upload_events(
            target,
            local_path,
            remote_path=remote_path,
            display_name=display_name,
            history_entry_id=history_entry_id,
            build_http_receive_command=self._build_http_receive_command,
            source=source,
            task_id=task_id,
            command=command,
            tab_id=tab_id,
            transfer_id=transfer_id,
            conflict_policy=conflict_policy,
            use_transfer_manager=use_transfer_manager,
        )
