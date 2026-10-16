import threading
import time
from typing import Callable


from core.utils.timeouts import normalize_positive_timeout
class CommandCancelledError(RuntimeError):
    """
    命令取消异常。
    """
    pass


class CommandTimeoutError(TimeoutError):
    """
    命令超时异常。
    """
    pass


class CommandExecutionContext:
    """
    单次命令执行上下文。

    职责：
    - 保存当前命令的取消事件
    - 提供 cancel handler / cleanup handler 注册能力
    - 承载当前命令的 timeout 配置与剩余时长计算
    - 承载当前命令的 cancel policy（支持/不支持取消）
    - 在收到取消请求时统一触发取消
    """

    def __init__(self, command_id: int, timeout: float | None = None):
        self.command_id = command_id
        self.started_at = time.monotonic()
        self.timeout = normalize_positive_timeout(timeout)
        self.cancel_event = threading.Event()

        self._lock = threading.RLock()
        self._cancel_handlers: list[Callable[[], None]] = []
        self._cleanup_handlers: list[Callable[[], None]] = []
        self._cancel_mode = 'none'
        self.cancel_state = 'running'
        self._cancel_observed = False
        self._completion_handlers = []
        self._cancel_unsupported_message = ''

    def set_timeout(self, timeout) -> None:
        with self._lock:
            normalized = normalize_positive_timeout(timeout)
            if normalized is not None:
                self.timeout = min(self.timeout, normalized) if self.timeout is not None else normalized

    def set_cancel_policy(self, mode: str = 'none', message: str = '') -> None:
        if mode not in ('none', 'cooperative', 'process'):
            raise ValueError(f'Invalid cancel mode: {mode}')
        with self._lock:
            self._cancel_mode = mode
            self._cancel_unsupported_message = str(message or '').strip()

    def get_cancel_policy(self) -> dict:
        with self._lock:
            return {'mode': self._cancel_mode, 'message': self._cancel_unsupported_message}

    def is_cancel_supported(self) -> bool:
        with self._lock:
            return self._cancel_mode != 'none'

    def get_cancel_unsupported_message(self) -> str:
        with self._lock:
            return self._cancel_unsupported_message

    def is_cancel_requested(self) -> bool:
        return self.cancel_event.is_set()

    def elapsed_seconds(self) -> float:
        return max(time.monotonic() - self.started_at, 0.0)

    def remaining_timeout(self, fallback_timeout=None) -> float | None:
        effective_timeout = self.timeout
        if effective_timeout is None:
            effective_timeout = normalize_positive_timeout(fallback_timeout)

        if effective_timeout is None:
            return None

        remaining = effective_timeout - self.elapsed_seconds()
        if remaining <= 0:
            return 0.0
        return remaining

    def resolve_timeout(self, fallback_timeout=None) -> float | None:
        remaining = self.remaining_timeout(fallback_timeout)
        if remaining is None:
            return None
        return max(remaining, 0.001)

    def is_timeout_expired(self, fallback_timeout=None) -> bool:
        remaining = self.remaining_timeout(fallback_timeout)
        if remaining is None:
            return False
        return remaining <= 0

    def add_cancel_handler(self, handler: Callable[[], None]):
        if not callable(handler):
            return

        should_call_now = False
        with self._lock:
            if self.cancel_event.is_set():
                should_call_now = True
            else:
                self._cancel_handlers.append(handler)

        if should_call_now:
            try:
                handler()
            except Exception:
                pass

    def add_cleanup_handler(self, handler: Callable[[], None]):
        if not callable(handler):
            return

        with self._lock:
            self._cleanup_handlers.append(handler)

    def request_cancel(self, on_completion=None) -> dict:
        with self._lock:
            if self.cancel_state in ('stopped', 'completed'):
                return {
                    'accepted': False, 'state': 'finished',
                    'message': 'Command is not running',
                }
            if self._cancel_mode == 'none':
                return {
                    'accepted': False, 'state': 'rejected',
                    'message': self._cancel_unsupported_message or 'Command does not support cancellation',
                }
            # Register before signalling cancellation: a handler may end the command
            # and clear its context before the caller can register separately.
            if on_completion is not None:
                self._completion_handlers.append(on_completion)
            already_requested = self.cancel_event.is_set()
            self.cancel_event.set()
            self.cancel_state = 'accepted'
            handlers = list(self._cancel_handlers) if not already_requested else []

        # A handler being invoked does not prove that the command stopped.
        if handlers:
            for handler in handlers:
                try:
                    handler()
                except Exception:
                    pass
        return {
            'accepted': True,
            'state': 'accepted',
            'already_cancelled': already_requested,
            'message': 'Cancellation accepted; command is still running',
        }

    def on_completion(self, handler):
        """Callback fires only when command invocation has returned, not on cancel ACK."""
        with self._lock:
            if self.cancel_state in ('stopped', 'completed'):
                state = self.cancel_state
            else:
                self._completion_handlers.append(handler)
                return
        handler(state)

    def finish(self, cancelled: bool = False):
        """Only an observed cancellation followed by command exit counts as stopped."""
        with self._lock:
            was_requested = self.cancel_event.is_set()
            self.cancel_state = 'stopped' if (was_requested and (cancelled or self._cancel_observed)) else 'completed'
            handlers = list(self._completion_handlers)
            self._completion_handlers.clear()
            state = self.cancel_state
        for handler in handlers:
            try:
                handler(state)
            except Exception:
                pass

    def raise_if_cancelled(self):
        if self.is_cancel_requested():
            with self._lock:
                self._cancel_observed = True
            raise CommandCancelledError('Command cancelled')

    def raise_if_timed_out(self, fallback_timeout=None):
        if self.is_timeout_expired(fallback_timeout=fallback_timeout):
            timeout_value = self.timeout
            if timeout_value is None:
                timeout_value = normalize_positive_timeout(fallback_timeout)
            if timeout_value is None:
                timeout_value = 0
            raise CommandTimeoutError(f'Command timed out after {timeout_value:g}s')

    def raise_if_interrupted(self, fallback_timeout=None):
        self.raise_if_cancelled()
        self.raise_if_timed_out(fallback_timeout=fallback_timeout)

    def run_cleanup(self):
        with self._lock:
            handlers = list(self._cleanup_handlers)
            self._cleanup_handlers.clear()

        for handler in reversed(handlers):
            try:
                handler()
            except Exception:
                pass









