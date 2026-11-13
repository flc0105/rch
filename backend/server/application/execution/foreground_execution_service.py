import json
from server.application.command.command_types import COMMAND_TYPE_COMMAND
from server.application.tasks.task_types import TASK_TYPE_COMMAND

class ForegroundExecutionService:
    """
    前台执行服务。

    职责：
    - 统一占用 / 释放 foreground task 槽
    - 在 foreground 语义下执行远程命令
    - 基于结果流提供 text/json 两类同步读取能力

    说明：
    - 不负责历史编排
    - 不直接依赖 server，只依赖底层 command_stream_service
    """

    def __init__(self, command_stream_service):
        self.command_stream_service = command_stream_service

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
        """
        统一前台执行入口：
        凡是前台同步等待 session.send_command() 结果流的请求，都必须走这里。
        """
        session = self.command_stream_service.get_connection(target)

        acquired_task = session.acquire_foreground_task(
            task_type=task_type,
            command=command,
            source=source,
            task_id=task_id,
        )

        effective_task_id = acquired_task.get('task_id', '') if isinstance(acquired_task, dict) else ''

        try:
            result_iter = self.command_stream_service.stream_command(
                session,
                command,
                command_type=command_type,
                extra=extra,
                payload=payload,
                domain=domain, action=action,
                history_entry_id=history_entry_id,
            )
            for item in result_iter:
                yield item
        finally:
            session.release_foreground_task(
                task_id=effective_task_id or task_id,
                command=command
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
        status, text = self.command_stream_service.collect_result(
            self.stream_foreground_command(
                target,
                command,
                command_type=command_type,
                extra=extra,
                payload=payload,
                domain=domain, action=action,
                history_entry_id=history_entry_id,
                task_type=task_type,
                source=source,
                task_id=task_id,
            )
        )

        if status != 1:
            raise RuntimeError(text or 'Remote command failed')

        return text

    def run_foreground_json_command(
        self,
        target,
        command: str,
        *,
        command_type: str = 'command',
        extra=None,
        payload=None,
        domain: str = '',
        action: str = '',
        history_entry_id: str = '',
        task_type: str = 'command',
        source: str = 'foreground',
        task_id: str = '',
    ) -> dict:
        text = self.run_foreground_text_command(
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

        try:
            payload = json.loads(text or '{}')
        except Exception as e:
            raise RuntimeError(f'Invalid remote JSON payload: {e}')

        if not isinstance(payload, dict):
            raise RuntimeError('Invalid remote JSON payload: expected object')

        return payload








