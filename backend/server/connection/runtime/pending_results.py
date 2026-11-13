"""Per-session request correlation; unsolicited output uses the separate message queue."""
import threading
from core.protocol.message_queue import MessageQueue


class PendingResults:
    def __init__(self):
        self._lock = threading.RLock()
        self._items = {}
        self._closed = False

    def register(self, request_id):
        with self._lock:
            if self._closed:
                raise ConnectionError('Client disconnected')
            if request_id in self._items:
                raise ValueError('Duplicate pending request ID')
            queue = MessageQueue()
            self._items[request_id] = [queue, False]
            return queue

    def deliver(self, request_id, status, result, eof, before_enqueue=None):
        with self._lock:
            item = self._items.get(request_id)
            if item is None or item[1]:
                return False
            if before_enqueue is not None:
                before_enqueue()
            item[1] = bool(eof)
            item[0].put(status, result, eof)
            return True

    def remove(self, request_id):
        with self._lock:
            self._items.pop(request_id, None)

    def close(self):
        with self._lock:
            self._closed = True
            for queue, finished in self._items.values():
                if not finished:
                    queue.put(0, None, 1)
            self._items.clear()
