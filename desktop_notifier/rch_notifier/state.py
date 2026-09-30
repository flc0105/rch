import json
from pathlib import Path


class CursorState:
    def __init__(self, path: Path):
        self.path = path
        self.last_event_id = ''
        self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                self.last_event_id = str(raw.get('last_event_id') or '').strip()
        except FileNotFoundError:
            self.last_event_id = ''
        except Exception:
            # A damaged local cursor must never prevent live notifications.
            self.last_event_id = ''

    def update(self, event_id: str):
        normalized_id = str(event_id or '').strip()
        if not normalized_id:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(self.path.name + '.tmp')
        tmp_path.write_text(
            json.dumps({'last_event_id': normalized_id}, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
        tmp_path.replace(self.path)
        self.last_event_id = normalized_id

    def clear(self):
        self.last_event_id = ''
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
