"""Correlate canonical Result events with pending Client requests."""
import queue
import threading


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
            result_queue = queue.Queue()
            self._items[request_id] = [result_queue, False]
            return result_queue

    def deliver(self, request_id, event, before_enqueue=None):
        """Enqueue an original Result event; completed closes this request once."""
        if not isinstance(event, dict) or event.get('event_type') not in (
                'started', 'progress', 'chunk', 'completed'):
            raise ValueError('Invalid Result event')
        with self._lock:
            item = self._items.get(request_id)
            if item is None or item[1]:
                return False
            if before_enqueue is not None:
                before_enqueue()
            item[1] = event['event_type'] == 'completed'
            item[0].put(event)
            return True

    def remove(self, request_id):
        with self._lock:
            self._items.pop(request_id, None)

    def close(self):
        with self._lock:
            self._closed = True
            for result_queue, finished in self._items.values():
                if not finished:
                    # Wake local waiters without adding a fabricated Client packet.
                    result_queue.put(None)
            self._items.clear()
