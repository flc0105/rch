import os
import re
from datetime import datetime

from core.protocol.result_envelope import ResultEvent
from core.protocol.result_envelope import ResultEnvelope
from core.utils.parsing import parse
from server.application.artifact.artifact_events import publish_artifact_created
from .wrapped_result import iter_inner_results


class CommandOutputBuiltinSupport:
    """
    saveout 内建命令支持。

    语义：
    - saveout <client-command>
    - 内部命令走现有 client command 规划/执行链路
    - 内部输出不直接显示到 terminal，而是完整写入 command_output artifact
    """

    ARTIFACT_TYPE = 'command_output'
    DEFAULT_CATEGORY = 'command_output'
    OUTPUT_TIME_FORMAT = '%Y%m%d_%H%M%S'

    def __init__(self, server, conn, plan_builder, plan_executor_factory, history_entry_id_provider, artifact_service, event_bus):
        self.server = server
        self.conn = conn
        self.plan_builder = plan_builder
        self.plan_executor_factory = plan_executor_factory
        self.history_entry_id_provider = history_entry_id_provider
        self.artifact_service = artifact_service
        self.event_bus = event_bus

    def _now(self):
        return datetime.now()

    def _get_session_info(self):
        return getattr(self.conn, 'session_info', None)

    def _get_runtime_task(self) -> dict:
        try:
            task = self.conn.get_foreground_task() or {}
            return task if isinstance(task, dict) else {}
        except Exception:
            return {}

    def _get_source_command_id(self):
        runtime_task = self._get_runtime_task()
        return runtime_task.get('command_id')




    def _build_extra(self, *, command: str, started_at: str, finished_at: str,
                     final_status: str) -> dict:
        return {
            'saved_from': 'saveout',
            'source_command': command,
            'started_at': started_at,
            'finished_at': finished_at,
            'final_status': final_status,
        }

    def _allocate_output_artifact(self, *, command: str, output_kind: str) -> dict:
        session_info = self._get_session_info()
        return self.artifact_service.allocate_command_output_artifact_path(
            output_kind=output_kind,
            machine_id=getattr(session_info, 'machine_id', '') or 'unknown_machine',
            source_command=command,
        )

    def _register_output_artifact(self, *, allocation: dict, command: str, output_kind: str, extra: dict) -> dict:
        session_info = self._get_session_info()
        artifact = self.artifact_service.register_command_output_artifact(
            allocation=allocation,
            output_kind=output_kind,
            hostname=getattr(session_info, 'hostname', '') or 'unknown_host',
            machine_id=allocation.get('machine_id') or getattr(session_info, 'machine_id', '') or 'unknown_machine',
            client_id=getattr(session_info, 'client_id', '') or '',
            addr=getattr(session_info, 'addr', '') or '',
            source_command=command,
            source_command_id=self._get_source_command_id(),
            extra=extra,
        )
        try:
            publish_artifact_created(self.event_bus, artifact)
        except Exception:
            pass  # Notification failure must not invalidate a saved artifact.
        return artifact

    def _build_inner_executor(self, command: str):
        name, arg = parse(command)

        if self.plan_builder.is_argument_command(command):
            plan = self.plan_builder.build_argument_command_plan(command)
        else:
            alias_plan = self.plan_builder.build_alias_plan(name, arg)
            plan = alias_plan or self.plan_builder.build_default_plan(command)

        plan_executor = self.plan_executor_factory()
        return plan_executor(plan)

    def _append_chunk(self, file_obj, text: str):
        if not text:
            return

        file_obj.write(text)

        # 远端结果通常按逻辑 chunk 返回，这里补换行保证流式输出可读。
        if not text.endswith('\n'):
            file_obj.write('\n')

    def saveout(self, command: str):
        inner_command = str(command or '').strip()
        if not inner_command:
            message = 'Usage: saveout <client-command>'
            envelope = ResultEnvelope(status='error', message=message).as_payload()
            yield ResultEvent(envelope, message)
            return

        output_kind = 'command'
        allocation = self._allocate_output_artifact(
            command=inner_command,
            output_kind=output_kind,
        )
        file_path = allocation['file_path']

        started = self._now()
        started_at = started.isoformat(timespec='seconds')
        final_status = 'interrupted'

        try:
            executor = self._build_inner_executor(inner_command)
            with open(file_path, 'w', encoding='utf-8', errors='replace') as file_obj:
                for item in iter_inner_results(executor()):
                    if item.terminal_status is not None:
                        final_status = item.terminal_status
                    self._append_chunk(file_obj, item.visible_text())
        except Exception as exc:
            final_status = 'error'
            with open(file_path, 'a', encoding='utf-8', errors='replace') as file_obj:
                self._append_chunk(file_obj, str(exc))

        finished = self._now()
        extra = self._build_extra(
            command=inner_command,
            started_at=started_at,
            finished_at=finished.isoformat(timespec='seconds'),
            final_status=final_status,
        )

        artifact = self._register_output_artifact(
            allocation=allocation,
            command=inner_command,
            output_kind=output_kind,
            extra=extra,
        )

        size = int(artifact.get('size') or 0)
        # File registration is not proof that the inner Client command succeeded.
        message = '\n'.join([
            f'saved to command_output: {artifact.get("original_name") or allocation.get("original_name") or "command_output.txt"}',
            f'artifact_id: {artifact.get("artifact_id", "")}',
            f'size: {size} bytes',
        ])
        envelope = ResultEnvelope(status=final_status, message=message).as_payload()
        yield ResultEvent(envelope, message)
