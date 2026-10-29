import threading
from collections import deque
import time
import uuid
from datetime import datetime


HTTP_CONTROL_COMMANDS = {'kill', 'relaunch', 'clone'}


class ControlCommandStore:
    # All HTTP control budgets are kept together for deployment tuning.
    CONTROL_TIMEOUT_SECONDS = {
        'kill': 60.0,
        'relaunch': 60.0,
        'clone': 60.0,
    }
    MAX_PENDING_COMMANDS = 32
    COMPLETED_OUTCOME_RETENTION_SECONDS = 300.0

    def __init__(self):
        self._commands_by_client = {}
        self._delivered_shutdown_by_client = {}
        self._outcomes_by_id = {}
        self._expiry_timers = {}
        self._on_timeout = None
        self._lock = threading.RLock()

    def _now_iso(self) -> str:
        return datetime.now().isoformat()

    def set_timeout_callback(self, callback):
        self._on_timeout = callback

    def _public_outcome(self, outcome):
        return {key: val for key, val in outcome.items() if key not in ('created_monotonic',)}

    def _expire_command(self, command_id):
        callback = None
        payload = None
        with self._lock:
            outcome = self._outcomes_by_id.get(command_id)
            if not outcome or outcome['status'] not in ('queued', 'received'):
                return
            outcome['status'] = 'timeout'
            seconds = self.CONTROL_TIMEOUT_SECONDS[outcome['command']]
            outcome['detail'] = f'Remote Control Watchdog did not respond within {seconds:g} seconds'
            cid = outcome['client_id']
            pending = self._commands_by_client.get(cid)
            if pending is not None:
                remaining = deque(item for item in pending if item['command_id'] != command_id)
                if remaining:
                    self._commands_by_client[cid] = remaining
                else:
                    self._commands_by_client.pop(cid, None)
            self._expiry_timers.pop(command_id, None)
            payload = self._public_outcome(outcome)
            callback = self._on_timeout
        if callback:
            callback(payload)

    def _finish_command_locked(self, command_id, status, detail=''):
        outcome = self._outcomes_by_id.get(command_id)
        if not outcome or (outcome['status'] not in ('queued', 'received') and not (status == 'online' and outcome['status'] == 'delivered')):
            return outcome
        outcome.update(status=status, detail=str(detail or '')[:240])
        timer = self._expiry_timers.pop(command_id, None)
        if timer:
            timer.cancel()
        return outcome

    def set_pending_command(self, client_id: str, command: str) -> dict:
        cid = str(client_id or '').strip()
        cmd = str(command or '').strip().lower()
        if not cid:
            raise ValueError('client_id is required')
        if cmd not in HTTP_CONTROL_COMMANDS:
            raise ValueError('Unsupported HTTP control action')
        payload = {'client_id': cid, 'command': cmd, 'command_id': uuid.uuid4().hex, 'created_at': self._now_iso()}
        with self._lock:
            # Retain recent acknowledgements for retries, but not every completed command forever.
            now = time.monotonic()
            for old_id, old in list(self._outcomes_by_id.items()):
                if old['status'] not in ('queued', 'received') and now - old['created_monotonic'] > self.COMPLETED_OUTCOME_RETENTION_SECONDS:
                    self._outcomes_by_id.pop(old_id, None)
            pending = self._commands_by_client.setdefault(cid, deque())
            if len(pending) >= self.MAX_PENDING_COMMANDS:
                raise ValueError('HTTP control queue is full')
            pending.append(payload)
            outcome = {**payload, 'status': 'queued', 'detail': '', 'created_monotonic': time.monotonic()}
            self._outcomes_by_id[payload['command_id']] = outcome
            timer = threading.Timer(self.CONTROL_TIMEOUT_SECONDS[cmd], self._expire_command, args=(payload['command_id'],))
            timer.daemon = True
            self._expiry_timers[payload['command_id']] = timer
            timer.start()
        return dict(payload)

    def pop_pending_command(self, client_id: str) -> dict | None:
        cid = str(client_id or '').strip()
        if not cid:
            return None
        with self._lock:
            pending = self._commands_by_client.get(cid)
            payload = pending.popleft() if pending else None
            if pending is not None and not pending:
                self._commands_by_client.pop(cid, None)
            if payload:
                if payload['command'] in ('kill', 'relaunch'):
                    self._delivered_shutdown_by_client[cid] = (payload['command'], time.monotonic())
                    # These actions terminate their own worker; receipt is the final acknowledgement.
                    self._finish_command_locked(payload['command_id'], 'delivered')
                else:
                    outcome = self._outcomes_by_id[payload['command_id']]
                    outcome['status'] = 'received'
        return dict(payload) if payload else None

    def acknowledge_control(self, client_id: str, command_id: str, status: str, detail: str = '') -> dict:
        cid = str(client_id or '').strip()
        if status not in ('delivered', 'failed'):
            raise ValueError('Unsupported HTTP control result')
        with self._lock:
            outcome = self._outcomes_by_id.get(command_id)
            if not outcome or outcome['client_id'] != cid or outcome['command'] != 'clone':
                raise ValueError('Unknown HTTP control request')
            if outcome['status'] in ('online', 'timeout', 'delivered', 'failed'):
                return self._public_outcome(outcome)
            if outcome['status'] != 'received':
                raise ValueError('HTTP control request has not been received')
            self._finish_command_locked(command_id, status, detail)
            return self._public_outcome(outcome)

    def take_delivered_shutdown(self, client_id: str, *, max_age: float = 120.0) -> str:
        with self._lock:
            delivered = self._delivered_shutdown_by_client.pop(str(client_id or '').strip(), None)
        if delivered and time.monotonic() - delivered[1] < max_age:
            return delivered[0]
        return ''


_CONTROL_COMMAND_STORE = ControlCommandStore()


def get_control_command_store() -> ControlCommandStore:
    return _CONTROL_COMMAND_STORE
