from core.protocol.control import validate_control_fields, ExecutionPolicy
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from threading import RLock, BoundedSemaphore
from typing import Callable


@dataclass(frozen=True)
class ControlActionRegistration:
    action: str
    handler: Callable
    policy: ExecutionPolicy
    prepare: Callable | None = None
    cancel_policy: str | Callable | None = None



class ClientControlDispatcher:
    """Dispatch registered domains without loading a command catalog."""

    def __init__(self, execution):
        self.execution = execution
        self._actions = {}
        self._lock = RLock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='control')
        self._slots = BoundedSemaphore(4)
        self._active = {}
        self._generation = 0
        self._closed = False

    def register(self, domain, action, handler, *, policy, prepare=None, cancel_policy=None):
        self._actions[domain, action] = ControlActionRegistration(action, handler, policy, prepare, cancel_policy)

    def policy(self, domain, action):
        registration = self._actions.get((domain, action)) if isinstance(domain, str) and isinstance(action, str) else None
        return registration.policy if registration else ExecutionPolicy.FOREGROUND

    def submit(self, data, route, send_result):
        request_id = data['id']
        if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id <= 0:
            return request_id, 0, 'Invalid Control request ID'
        try:
            validate_control_fields(data['domain'], data['action'], data['payload'])
        except (ValueError, KeyError):
            return request_id, 0, 'Invalid Control request'
        registration = self._actions[data['domain'], data['action']]
        if registration.prepare:
            try:
                data = {**data, 'payload': registration.prepare(registration.action, data['payload'])}
            except Exception as exc:
                return request_id, 0, str(exc)
        if not self._slots.acquire(blocking=False):
            return request_id, 0, 'Independent Control capacity exhausted'
        with self._lock:
            if self._closed or request_id in self._active:
                self._slots.release()
                return request_id, 0, 'Independent Control request unavailable'
            generation = self._generation
            self._active[request_id] = generation
            self.prepare(request_id, data['domain'], data['action'], data['payload'])
        def work():
            try:
                try:
                    result = route(data)
                except Exception as exc:
                    result = request_id, 0, str(exc)
                with self._lock:
                    current = generation == self._generation and not self._closed
                if current and result:
                    # The connection object belongs to this session only; it is
                    # never reused by a reconnect.
                    send_result(*result)
            finally:
                self.execution.context_store.clear(request_id)
                with self._lock:
                    self._active.pop(request_id, None)
                self._slots.release()
        try:
            self._pool.submit(work)
        except RuntimeError:
            with self._lock:
                self._active.pop(request_id, None)
            self.execution.context_store.clear(request_id)
            self._slots.release()
            return request_id, 0, 'Independent Control executor unavailable'
        return None

    def disconnect(self):
        with self._lock:
            self._generation += 1
            self._closed = True
            active = list(self._active)
        for request_id in active:
            self.execution.cancel(request_id)
        self._pool.shutdown(wait=False)


    def prepare(self, request_id, domain, action, payload):
        if not isinstance(request_id, int) or not isinstance(domain, str):
            return
        try:
            validate_control_fields(domain, action, payload)
        except ValueError:
            return
        registration = self._actions.get((domain, action))
        if registration is None:
            return
        policy = registration.cancel_policy
        mode = policy(registration.action, payload) if callable(policy) else policy
        if mode is not None:
            context = self.execution.context_store.get_or_create(request_id)
            message = 'Current execution mode does not support cancellation' if mode == 'none' else ''
            context.set_cancel_policy(mode, message=message)

    def execute(self, request_id, domain, action, payload, options=None):
        validate_control_fields(domain, action, payload)
        registration = self._actions.get((domain, action))
        if registration is None:
            return 0, f'Unsupported Control action: {domain}/{action}'
        return self.execution.run(request_id, lambda scope: registration.handler(scope, registration.action, payload), options)
