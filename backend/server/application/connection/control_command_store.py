import threading
from datetime import datetime


HTTP_CONTROL_COMMANDS = {'kill', 'relaunch', 'clone'}


class ControlCommandStore:
    def __init__(self):
        self._commands_by_client = {}
        self._lock = threading.RLock()


    def _now_iso(self) -> str:
        return datetime.now().isoformat()


    def set_pending_command(self, client_id: str, command: str) -> dict:
        client_id_text = str(client_id or '').strip()
        command_text = str(command or '').strip().lower()

        if not client_id_text:
            raise ValueError('client_id is required')

        if command_text not in HTTP_CONTROL_COMMANDS:
            raise ValueError('Unsupported HTTP control action')

        payload = {
            'client_id': client_id_text,
            'command': command_text,
            'created_at': self._now_iso(),
        }

        with self._lock:
            self._commands_by_client[client_id_text] = payload

        return dict(payload)


    def pop_pending_command(self, client_id: str) -> dict | None:
        client_id_text = str(client_id or '').strip()
        if not client_id_text:
            return None

        with self._lock:
            payload = self._commands_by_client.pop(client_id_text, None)

        if payload is None:
            return None

        return dict(payload)


_CONTROL_COMMAND_STORE = ControlCommandStore()


def get_control_command_store() -> ControlCommandStore:
    return _CONTROL_COMMAND_STORE