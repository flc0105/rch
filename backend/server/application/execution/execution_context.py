from dataclasses import dataclass, field
from typing import Any
from core.protocol.control import ControlRequest


@dataclass
class ExecutionContext:
    """统一命令执行上下文。"""

    session: Any
    command: str
    source: str = 'cli'
    task_type: str = 'command'
    task_id: str = ''
    history_entry_id: str = ''
    command_id: int | None = None
    client_id: str = ''
    tab_id: str = ''
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_session(
        cls,
        session,
        command: str,
        *,
        source: str = 'cli',
        task_type: str = 'command',
        task_id: str = '',
        history_entry_id: str = '',
        command_id: int | None = None,
        tab_id: str = '',
        metadata: dict | None = None,
    ):
        session_info = getattr(session, 'session_info', None)
        client_id = getattr(session_info, 'client_id', '') or ''
        return cls(
            session=session,
            command=(command or '').strip(),
            source=(source or '').strip() or 'cli',
            task_type=(task_type or '').strip() or 'command',
            task_id=(task_id or '').strip(),
            history_entry_id=(history_entry_id or '').strip(),
            command_id=command_id,
            client_id=client_id,
            tab_id=(tab_id or '').strip(),
            metadata=dict(metadata or {}),
        )

    def bind_command_id(self, command_id: int | None):
        self.command_id = command_id
        return self


@dataclass
class TaskExecutionContext(ExecutionContext):
    """Web task 执行上下文。"""

    control: ControlRequest | None = None

    @classmethod
    def from_task(
        cls,
        session,
        task: dict,
        command: str,
        *,
        source: str,
        task_type: str,
        metadata: dict | None = None,
    ):
        task_payload = dict(task or {})
        merged_metadata = dict(metadata or {})
        merged_metadata.setdefault('created_at', task_payload.get('created_at') or '')
        return cls.from_session(
            session,
            command,
            source=source,
            task_type=task_type,
            task_id=task_payload.get('task_id') or '',
            history_entry_id=task_payload.get('history_entry_id') or '',
            tab_id=task_payload.get('tab_id') or '',
            metadata=merged_metadata,
        )