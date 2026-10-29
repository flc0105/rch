import threading
from collections import deque
import time
import uuid
from datetime import datetime


HTTP_CONTROL_COMMANDS = {'kill', 'relaunch', 'clone', 'resume'}
RESUME_TIMEOUT_SECONDS = 60.0


class ControlCommandStore:
    def __init__(self):
        self._commands_by_client = {}
        self._delivered_shutdown_by_client = {}
        self._last_poll_by_client = {}
        self._pause_by_client = {}
        self._resume_outcomes = {}
        self._lock = threading.RLock()

    def _now_iso(self) -> str:
        return datetime.now().isoformat()

    def _reachable_locked(self, client_id, *, max_age=35.0):
        last_poll = self._last_poll_by_client.get(client_id)
        if last_poll is None:
            return False
        if time.monotonic() - last_poll > max_age:
            self._last_poll_by_client.pop(client_id, None)
            self._pause_by_client.pop(client_id, None)
            return False
        return True

    def _expire_resume_locked(self, cid: str):
        outcome = self._resume_outcomes.get(cid)
        if not outcome or outcome.get('status') not in ('queued', 'received'):
            return
        since = outcome.get('created_monotonic')
        if since is None or time.monotonic() - since < RESUME_TIMEOUT_SECONDS:
            return
        outcome.update(status='timeout', detail='Remote Watchdog did not respond within 60 seconds')
        pending = self._commands_by_client.get(cid)
        if pending is not None:
            self._commands_by_client[cid] = deque(
                command for command in pending if command.get('command_id') != outcome['command_id']
            )
            if not self._commands_by_client[cid]:
                self._commands_by_client.pop(cid, None)

    def note_watchdog_poll(self, client_id: str, paused: bool):
        # The Worker sends this only after a successful authenticated local IPC
        # probe to its parent process. No extra HTTP heartbeat is necessary.
        cid = str(client_id or '').strip()
        if not cid:
            return
        with self._lock:
            self._last_poll_by_client[cid] = time.monotonic()
            self._pause_by_client[cid] = bool(paused)

    def clear_watchdog_reachability(self, client_id: str):
        cid = str(client_id or '').strip()
        with self._lock:
            self._last_poll_by_client.pop(cid, None)
            self._pause_by_client.pop(cid, None)

    def watchdog_status(self, client_id: str) -> dict:
        cid = str(client_id or '').strip()
        with self._lock:
            self._expire_resume_locked(cid)
            reachable = self._reachable_locked(cid)
            return {
                'reachable': reachable,
                'paused': reachable and self._pause_by_client.get(cid) is True,
                'resume': {key: val for key, val in (self._resume_outcomes.get(cid) or {}).items() if key != 'created_monotonic'},
            }

    def is_watchdog_reachable(self, client_id: str, *, max_age: float = 35.0) -> bool:
        with self._lock:
            return self._reachable_locked(str(client_id or '').strip(), max_age=max_age)

    def set_pending_command(self, client_id: str, command: str) -> dict:
        cid = str(client_id or '').strip()
        cmd = str(command or '').strip().lower()
        if not cid:
            raise ValueError('client_id is required')
        if cmd not in HTTP_CONTROL_COMMANDS:
            raise ValueError('Unsupported HTTP control action')
        payload = {'client_id': cid, 'command': cmd, 'command_id': uuid.uuid4().hex, 'created_at': self._now_iso()}
        with self._lock:
            self._expire_resume_locked(cid)
            if cmd == 'resume':
                if not self._reachable_locked(cid) or not self._pause_by_client.get(cid):
                    raise ValueError('Client is not confirmed paused and reachable via Remote Watchdog')
                existing = self._resume_outcomes.get(cid) or {}
                if existing.get('status') in ('queued', 'received'):
                    raise ValueError('Resume request is already pending for this Client')
            pending = self._commands_by_client.setdefault(cid, deque())
            if len(pending) >= 32:
                raise ValueError('HTTP control queue is full')
            pending.append(payload)
            if cmd == 'resume':
                self._resume_outcomes[cid] = {'command_id': payload['command_id'], 'status': 'queued', 'detail': '', 'created_monotonic': time.monotonic()}
        return dict(payload)

    def pop_pending_command(self, client_id: str) -> dict | None:
        cid = str(client_id or '').strip()
        if not cid:
            return None
        with self._lock:
            self._expire_resume_locked(cid)
            pending = self._commands_by_client.get(cid)
            payload = pending.popleft() if pending else None
            if pending is not None and not pending:
                self._commands_by_client.pop(cid, None)
            if payload and payload['command'] in ('kill', 'relaunch'):
                self._delivered_shutdown_by_client[cid] = (payload['command'], time.monotonic())
                self._last_poll_by_client.pop(cid, None)
                self._pause_by_client.pop(cid, None)
            if payload and payload['command'] == 'resume':
                self._resume_outcomes[cid].update(status='received')
        return dict(payload) if payload else None

    def acknowledge_resume(self, client_id: str, command_id: str, status: str, detail: str = '') -> dict:
        cid = str(client_id or '').strip()
        if status not in ('delivered', 'failed'):
            raise ValueError('Unsupported resume result')
        with self._lock:
            self._expire_resume_locked(cid)
            current = self._resume_outcomes.get(cid)
            if not current or current.get('command_id') != command_id:
                raise ValueError('Unknown resume request')
            if current.get('status') in ('online', 'timeout'):
                return {key: val for key, val in current.items() if key != 'created_monotonic'}
            if current.get('status') != 'received':
                raise ValueError('Already acknowledged resume request')
            current.update(status=status, detail=str(detail or '')[:240])
            return {key: val for key, val in current.items() if key != 'created_monotonic'}

    def mark_connected(self, client_id: str):
        cid = str(client_id or '').strip()
        with self._lock:
            self._pause_by_client[cid] = False
            self._expire_resume_locked(cid)
            outcome = self._resume_outcomes.get(cid)
            if outcome and outcome.get('status') in ('queued', 'received', 'delivered'):
                outcome.update(status='online', detail='')

    def take_delivered_shutdown(self, client_id: str, *, max_age: float = 120.0) -> str:
        with self._lock:
            delivered = self._delivered_shutdown_by_client.pop(str(client_id or '').strip(), None)
        if delivered and time.monotonic() - delivered[1] < max_age:
            return delivered[0]
        return ''


_CONTROL_COMMAND_STORE = ControlCommandStore()


def get_control_command_store() -> ControlCommandStore:
    return _CONTROL_COMMAND_STORE
