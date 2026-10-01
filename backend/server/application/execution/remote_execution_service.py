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

    HTTP_RECEIVE_COMMAND_NAME = 'receive_http_upload'

    def __init__(self, server, artifact_service=None, transfer_service=None):
        self.server = server
        self.artifact_service = artifact_service
        self.transfer_service = transfer_service
        self.history_orchestrator = getattr(server, 'command_history_orchestrator', None)

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

    def create_history_entry(self, target, command: str, source: str = 'cli', should_record: bool = True, task_type: str = '') -> str:
        session = self.get_connection(target)

        if self.history_orchestrator is not None:
            return self.history_orchestrator.begin_execution(
                session,
                command,
                source=source,
                should_record=should_record,
                task_type=task_type,
            )

        if not should_record:
            return ''

        command_text = (command or '').strip()
        if not command_text:
            return ''

        return self.server.command_history.create_entry_for_connection(
            session,
            command_text,
            source=source
        )

    def finalize_history_entry(self, target, entry_id: str, ok: bool, cwd_end: str = ''):
        if not entry_id:
            return

        session = self.get_connection(target)

        if self.history_orchestrator is not None:
            self.history_orchestrator.finalize_execution(
                session,
                entry_id,
                ok,
                cwd_end=cwd_end
            )
            return

        self.server.command_history.finish_entry(
            entry_id,
            ok=ok,
            cwd_end=cwd_end or session.session_info.cwd
        )

    def append_history_output(self, target, entry_id: str, status: int, text: str, eof: int = 0):
        if not entry_id:
            return

        session = self.get_connection(target)

        if self.history_orchestrator is not None:
            self.history_orchestrator.append_output(
                session,
                entry_id,
                status,
                text,
                eof
            )
            return

        self.server.command_history.append_output(
            entry_id,
            status,
            text,
            eof=eof
        )

    def stream_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        history_entry_id: str = '',
    ):
        return self.command_stream_service.stream_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            history_entry_id=history_entry_id,
        )

    def run_text_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        history_entry_id: str = '',
    ) -> str:
        return self.command_stream_service.run_text_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            history_entry_id=history_entry_id,
        )

    def run_json_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
        history_entry_id: str = '',
    ) -> dict:
        return self.command_stream_service.run_json_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
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
        history_entry_id: str = '',
        task_type: str = TASK_TYPE_COMMAND,
        source: str = 'foreground',
        task_id: str = '',
    ) -> str:
        return self.foreground_execution_service.run_foreground_text_command(
            target,
            command,
            command_type=command_type,
            extra=extra,
            history_entry_id=history_entry_id,
            task_type=task_type,
            source=source,
            task_id=task_id,
        )

    def run_foreground_json_command(
        self,
        target,
        command: str,
        *,
        command_type: str = COMMAND_TYPE_COMMAND,
        extra=None,
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
            history_entry_id=history_entry_id,
            task_type=task_type,
            source=source,
            task_id=task_id,
        )

    def iter_upload_events(
        self,
        target,
        local_path: str,
        *,
        remote_path: str = '',
        history_entry_id: str = '',
        source: str = 'web',
        task_id: str = '',
        command: str = '',
        tab_id: str = '',
        transfer_id: str = '',
        use_transfer_manager: bool = False,
    ):
        return self.upload_execution_service.iter_upload_events(
            target,
            local_path,
            remote_path=remote_path,
            history_entry_id=history_entry_id,
            build_http_receive_command=self._build_http_receive_command,
            source=source,
            task_id=task_id,
            command=command,
            tab_id=tab_id,
            transfer_id=transfer_id,
            use_transfer_manager=use_transfer_manager,
        )
