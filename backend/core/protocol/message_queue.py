import queue
import threading
from typing import Any, Optional, Tuple


MessageItem = Tuple[int, Any, int]


class BaseThreadSafeQueue:
    def __init__(self):
        self._queue = queue.Queue()
        self._lock = threading.Lock()

    def _peek(self) -> Optional[Any]:
        with self._lock:
            if self._queue.qsize() == 0:
                return None
            return self._queue.queue[0]

    def _clear_internal(self) -> None:
        with self._lock:
            self._queue.queue.clear()

    def _get_by_index(self, index: int) -> Any:
        with self._lock:
            return self._queue.queue[index]

    def clear(self) -> None:
        self._clear_internal()

    def empty(self) -> bool:
        return self._queue.empty()

    def __len__(self) -> int:
        return self._queue.qsize()

    def __getitem__(self, index: int) -> Any:
        return self._get_by_index(index)


class MessageQueue(BaseThreadSafeQueue):
    def get(self, block: bool = True, timeout: Optional[float] = None) -> MessageItem:
        return self._queue.get(block=block, timeout=timeout)

    def peek_first(self) -> Optional[MessageItem]:
        return self._peek()

    def put(self, status: int, message: Any, end: int = 1) -> None:
        self._queue.put((status, message, end))
