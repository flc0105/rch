"""One waiting managed-transfer connection on a Bind listener."""
import hmac
import queue
import threading

from core.protocol.auxiliary import close_socket


class FileConnectionSlot:
    def __init__(self, token):
        self.token = token
        self._queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._claimed = False
        self._closed = False

    def offer(self, sock, token):
        with self._lock:
            if (self._closed or self._claimed or not isinstance(token, str)
                    or not hmac.compare_digest(self.token.encode(), token.encode())):
                return False
            self._claimed = True
            self._queue.put_nowait(sock)
            return True

    def take(self, timeout):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        with self._lock:
            self._closed = True
            try:
                sock = self._queue.get_nowait()
            except queue.Empty:
                return
            close_socket(sock)
