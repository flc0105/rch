import threading

from core.utils.timeouts import normalize_positive_timeout
from client.commands.runtime.context import CommandExecutionContext


class CommandExecutionContextStore:
    """
    命令执行上下文存储。

    职责：
    - 统一管理 CommandExecutionContext 的创建、复用、清理
    - 统一处理 timeout 提取与取消请求
    """

    def __init__(self):
        self._execution_contexts = {}
        self._context_lock = threading.RLock()

    def extract_timeout(self, options=None):
        if not isinstance(options, dict):
            return None

        # 这里只提取显式下发的 timeout。
        # COMMAND_DEFAULT_TIMEOUT 作为兜底 fallback 在 CommandRuntimeMixin 内处理，
        # 避免创建 context 时就覆盖 shell / stream / HTTP 的专用 timeout。
        if '_timeout' in options:
            return normalize_positive_timeout(options.get('_timeout'))
        if 'timeout' in options:
            return normalize_positive_timeout(options.get('timeout'))
        return None

    def get_or_create(self, command_id, timeout=None):
        normalized_timeout = normalize_positive_timeout(timeout)

        with self._context_lock:
            context = self._execution_contexts.get(command_id)
            if context is None:
                context = CommandExecutionContext(command_id, timeout=normalized_timeout)
                self._execution_contexts[command_id] = context
            elif normalized_timeout is not None:
                context.set_timeout(normalized_timeout)
            return context

    def clear(self, command_id):
        with self._context_lock:
            context = self._execution_contexts.pop(command_id, None)

        if context is not None:
            try:
                context.run_cleanup()
            except Exception:
                pass

    def cancel(self, command_id: int) -> dict:
        with self._context_lock:
            context = self._execution_contexts.get(command_id)

        if context is None:
            return {
                'accepted': False,
                'message': 'Command is not running',
            }

        return context.request_cancel()








