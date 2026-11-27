from dataclasses import dataclass


class WebTaskStatus:
    RUNNING = 'running'
    CANCELLING = 'cancelling'
    SUCCESS = 'success'
    PARTIAL = 'partial'
    ERROR = 'error'
    CANCELLED = 'cancelled'
    TIMED_OUT = 'timed_out'
    INTERRUPTED = 'interrupted'

    ACTIVE_STATUSES = {
        RUNNING,
        CANCELLING,
    }

    TERMINAL_STATUSES = {
        SUCCESS,
        PARTIAL,
        ERROR,
        CANCELLED,
        TIMED_OUT,
        INTERRUPTED,
    }


@dataclass
class TaskStreamSummary:
    """Track explicit execution outcomes, never presentation text."""
    terminal_status: str = ''

    def mark_cancelled(self):
        self.terminal_status = WebTaskStatus.CANCELLED

    def mark_exception(self, exc=None):
        self.terminal_status = (WebTaskStatus.TIMED_OUT if isinstance(exc, TimeoutError) else
                                WebTaskStatus.INTERRUPTED if isinstance(exc, (ConnectionError, EOFError)) else
                                WebTaskStatus.ERROR)

    def mark_dispatch_failure(self, reason: str):
        self.terminal_status = reason if reason in WebTaskStatus.TERMINAL_STATUSES else WebTaskStatus.ERROR

    def mark_completed(self, ok: bool):
        if not self.terminal_status:
            self.terminal_status = WebTaskStatus.SUCCESS if ok else WebTaskStatus.ERROR

    def resolve_final_status(self) -> str:
        return self.terminal_status or WebTaskStatus.INTERRUPTED
