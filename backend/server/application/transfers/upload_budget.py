"""Process-wide admission budget for temporary upload bytes and concurrent intake."""
from contextlib import contextmanager
from threading import Lock


class UploadBudget:
    def __init__(self, *, max_bytes, max_slots, max_owner_slots):
        if min(max_bytes, max_slots, max_owner_slots) <= 0:
            raise ValueError('Upload staging limits must be positive')
        self.max_bytes = max_bytes
        self.max_slots = max_slots
        self.max_owner_slots = max_owner_slots
        self._lock = Lock()
        self._leases = {}
        self._bytes = 0

    def acquire(self, size, owner=''):
        if type(size) is not int or size < 0:
            raise ValueError('Invalid upload reservation size')
        with self._lock:
            if size > self.max_bytes - self._bytes:
                raise ValueError('Upload staging byte limit reached; wait for active uploads to finish')
            if len(self._leases) >= self.max_slots:
                raise ValueError('Upload staging concurrency limit reached; wait for active uploads to finish')
            if owner and sum(existing_owner == owner for _, existing_owner in self._leases.values()) >= self.max_owner_slots:
                raise ValueError('Device upload staging concurrency limit reached; wait for active uploads to finish')
            token = object()
            self._leases[token] = (size, owner)
            self._bytes += size
            return token

    def release(self, token):
        with self._lock:
            lease = self._leases.pop(token, None)
            if lease is not None:
                self._bytes -= lease[0]

    @contextmanager
    def reserve(self, size, owner=''):
        token = self.acquire(size, owner)
        try:
            yield
        finally:
            self.release(token)
