from client.runtime.execution.context_store import ExecutionContextStore
from client.runtime.execution.scope import ExecutionScope
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


class ExecutionRuntime:
    """Single lifecycle and cancellation store for all foreground entries."""

    def __init__(self, socket):
        self.socket = socket
        self.context_store = ExecutionContextStore()

    def execute(self, request_id, invoke):
        try:
            return invoke()
        finally:
            context = self.context_store.get_existing(request_id)
            if context is not None:
                context.finish()
            self.context_store.clear(request_id)

    def run(self, request_id, invoke, options=None):
        def dispatch():
            context = self.context_store.get_or_create(request_id, timeout=self.context_store.extract_timeout(options))
            # Pre-registered cancellation context may have waited in the inbound queue.
            import time
            context.started_at = time.monotonic()
            scope = ExecutionScope(self.socket, context)
            try:
                scope._checkpoint()
                return invoke(scope)
            except CommandCancelledError:
                return 0, {'event_type': 'cancelled', 'text': 'Command cancelled'}
            except CommandTimeoutError:
                return 0, {'event_type': 'error', 'failure_reason': 'timed_out', 'text': 'Command timed out'}
        return self.execute(request_id, dispatch)

    def cancel(self, request_id, on_completion=None):
        return self.context_store.cancel(request_id, on_completion=on_completion)

    def on_completion(self, request_id, callback):
        context = self.context_store.get_existing(request_id)
        if context is None:
            return False
        context.on_completion(callback)
        return True
