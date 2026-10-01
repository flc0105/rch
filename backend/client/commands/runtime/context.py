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
        self._cancel_supported = True
        self._cancel_unsupported_message = ''

    def set_timeout(self, timeout) -> None:
        with self._lock:
            self.timeout = normalize_positive_timeout(timeout)

    def set_cancel_policy(self, supported: bool = True, message: str = '') -> None:
        with self._lock:
            self._cancel_supported = bool(supported)
            self._cancel_unsupported_message = str(message or '').strip()

    def get_cancel_policy(self) -> dict:
        with self._lock:
            return {
                'supported': self._cancel_supported,
                'message': self._cancel_unsupported_message,
            }

    def is_cancel_supported(self) -> bool:
        with self._lock:
            return self._cancel_supported

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

    def request_cancel(self) -> dict:
        policy = self.get_cancel_policy()
        if not policy.get('supported', True):
            return {
                'accepted': False,
                'already_cancelled': self.cancel_event.is_set(),
                'message': policy.get('message') or 'Command does not support cancellation',
            }

        handlers = []

        with self._lock:
            already_cancelled = self.cancel_event.is_set()
            self.cancel_event.set()
            handlers = list(self._cancel_handlers)

        for handler in handlers:
            try:
                handler()
            except Exception:
                pass

        return {
            'accepted': True,
            'already_cancelled': already_cancelled,
            'message': 'Cancel requested',
        }

    def raise_if_cancelled(self):
        if self.is_cancel_requested():
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









