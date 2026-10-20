import os
import re
from datetime import datetime

from core.utils.parsing import parse


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

    def __init__(self, server, conn, plan_builder, plan_executor_factory, history_entry_id_provider):
        self.server = server
        self.conn = conn
        self.plan_builder = plan_builder
        self.plan_executor_factory = plan_executor_factory
        self.history_entry_id_provider = history_entry_id_provider

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




    def _build_extra(self, *, command: str, wrapper_command: str, started_at: str, finished_at: str,
                     duration_ms: int, final_status: str, inner_status: int) -> dict:
        runtime_task = self._get_runtime_task()
        return {
            'source': 'builtin_saveout',
            'source_command': command,
            'wrapper_command': wrapper_command,
            'source_history_entry_id': self.history_entry_id_provider() or '',
            'source_task_id': runtime_task.get('task_id') or '',
            'started_at': started_at,
            'finished_at': finished_at,
            'duration_ms': duration_ms,
            'final_status': final_status,
            'inner_status': inner_status,
        }

    def _allocate_output_artifact(self, *, command: str, category: str) -> dict:
        session_info = self._get_session_info()
        return self.server.web_service.artifact_api.allocate_command_output_artifact_path(
            category=category,
            machine_id=getattr(session_info, 'machine_id', '') or 'unknown_machine',
            source_command=command,
        )

    def _register_output_artifact(self, *, allocation: dict, command: str, category: str, extra: dict) -> dict:
        session_info = self._get_session_info()
        return self.server.web_service.artifact_api.register_command_output_artifact(
            allocation=allocation,
            category=category,
            hostname=getattr(session_info, 'hostname', '') or 'unknown_host',
            machine_id=allocation.get('machine_id') or getattr(session_info, 'machine_id', '') or 'unknown_machine',
            client_id=getattr(session_info, 'client_id', '') or '',
            addr=getattr(session_info, 'addr', '') or '',
            source='builtin_saveout',
            source_command=command,
            source_command_id=self._get_source_command_id(),
            extra=extra,
        )

    def _build_inner_executor(self, command: str):
        name, arg = parse(command)

        if self.plan_builder.is_argument_command(command):
            plan = self.plan_builder.build_argument_command_plan(command)
        else:
            alias_plan = self.plan_builder.build_alias_plan(name, arg)
            plan = alias_plan or self.plan_builder.build_default_plan(command)

        plan_executor = self.plan_executor_factory()
        return plan_executor(plan)

    def _coerce_output_text(self, result) -> str:
        if result is None:
            return ''

        if isinstance(result, dict):
            text = result.get('text')
            if text is None:
                text = result.get('message')
            if text is None:
                text = str(result)
            return str(text)

        return str(result)

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
            yield 0, 'Usage: saveout <client-command>'
            return

        wrapper_command = f'saveout {inner_command}'
        category = self.DEFAULT_CATEGORY
        allocation = self._allocate_output_artifact(
            command=inner_command,
            category=category,
        )
        file_path = allocation['file_path']

        started = self._now()
        started_at = started.isoformat(timespec='seconds')
        inner_status = 1
        final_status = 'success'

        try:
            executor = self._build_inner_executor(inner_command)
            with open(file_path, 'w', encoding='utf-8', errors='replace') as file_obj:
                for item in executor():
                    status = item[0] if item else 0
                    result = item[1] if item and len(item) > 1 else ''
                    inner_status = int(status or 0)

                    if inner_status == 0:
                        final_status = 'error'

                    self._append_chunk(file_obj, self._coerce_output_text(result))
        except Exception as exc:
            inner_status = 0
            final_status = 'error'
            with open(file_path, 'a', encoding='utf-8', errors='replace') as file_obj:
                self._append_chunk(file_obj, str(exc))

        finished = self._now()
        extra = self._build_extra(
            command=inner_command,
            wrapper_command=wrapper_command,
            started_at=started_at,
            finished_at=finished.isoformat(timespec='seconds'),
            duration_ms=int((finished - started).total_seconds() * 1000),
            final_status=final_status,
            inner_status=inner_status,
        )

        artifact = self._register_output_artifact(
            allocation=allocation,
            command=inner_command,
            category=category,
            extra=extra,
        )

        # saveout already creates a registered command_output artifact. Attach its
        # existing reference to the dispatched Activity without copying content.
        activity_id = self.history_entry_id_provider() or ''
        history = getattr(self.server, 'command_history_orchestrator', None)
        if activity_id and history is not None and artifact:
            history.history_store.append_file_for_connection(self.conn, activity_id, artifact)

        size = int(artifact.get('size') or 0)
        # File registration is not proof that the inner Client command succeeded.
        yield (1 if final_status == 'success' else 0), '\n'.join([
            f'saved to command_output: {artifact.get("original_name") or allocation.get("original_name") or "command_output.txt"}',
            f'artifact_id: {artifact.get("artifact_id", "")}',
            f'size: {size} bytes',
        ])