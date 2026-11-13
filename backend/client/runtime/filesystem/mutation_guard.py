"""Serialize filesystem mutations that share the Client's local filesystem."""
from contextlib import contextmanager
from threading import Lock

_mutation_lock = Lock()


@contextmanager
def filesystem_mutation(checkpoint):
    # A cancelled request must not mutate the filesystem after waiting for a writer.
    while not _mutation_lock.acquire(timeout=0.1):
        checkpoint()
    try:
        checkpoint()
        yield
    finally:
        _mutation_lock.release()
