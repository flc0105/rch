"""One-shot process lifecycle request shared by the Web API and run_web entrypoint."""

import secrets
import threading


class ServerLifecycle:
    def __init__(self):
        self.instance_id = secrets.token_hex(16)
        self._lock = threading.Lock()
        self._action = None
        self._ready = threading.Event()

    @property
    def action(self):
        with self._lock:
            return self._action

    def reserve(self, action):
        if action not in ('shutdown', 'restart'):
            raise ValueError('Invalid server lifecycle action')
        with self._lock:
            if self._action is not None:
                return False
            self._action = action
            return True

    def activate(self):
        """Called when the accepted HTTP response has finished sending."""
        self._ready.set()

    def wait(self):
        self._ready.wait()
        return self.action
