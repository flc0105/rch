from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompletionContext:
    """
    Command autocomplete 上下文。

    说明：
    - raw_input 保留用户输入原文
    - command_name 是首个 token，用于 provider 分发
    - argument_text 是命令名后的参数原文
    - current_token 是光标所在参数片段，当前只按末尾输入处理
    - metadata 用于 server/client 传递额外上下文，不参与通用解析
    """
    raw_input: str = ''
    command_name: str = ''
    argument_text: str = ''
    current_token: str = ''
    cursor_position: int = 0
    max_results: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'raw_input': self.raw_input,
            'command_name': self.command_name,
            'argument_text': self.argument_text,
            'current_token': self.current_token,
            'cursor_position': self.cursor_position,
            'max_results': self.max_results,
            'metadata': dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict | None):
        data = payload if isinstance(payload, dict) else {}
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
        return cls(
            raw_input=str(data.get('raw_input') or ''),
            command_name=str(data.get('command_name') or '').strip().lower(),
            argument_text=str(data.get('argument_text') or ''),
            current_token=str(data.get('current_token') or ''),
            cursor_position=_coerce_int(data.get('cursor_position'), 0),
            max_results=_coerce_int(data.get('max_results'), 50),
            metadata=dict(metadata),
        )


@dataclass
class CompletionCandidate:
    """
    统一 autocomplete candidate。

    title:       下拉展示标题，也是前端筛选依据。
    insert_text:选中后写入 input 的文本。
    description:下拉说明文案。
    """
    title: str
    insert_text: str
    description: str = ''
    source: str = ''
    group: str = ''
    kind: str = 'command'
    name: str = ''
    priority: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        title = str(self.title or self.insert_text or self.name or '').strip()
        insert_text = str(self.insert_text or title).strip()
        name = insert_text
        payload = {
            'name': name,
            'title': title,
            'value': insert_text,
            'insert_text': insert_text,
            'help': str(self.description or '').strip(),
            'group': str(self.group or '').strip(),
            'source': str(self.source or '').strip(),
            'kind': str(self.kind or 'command').strip(),
            'priority': int(self.priority or 100),
        }
        if self.metadata:
            payload.update(self.metadata)
        return payload


def _coerce_int(value, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback
