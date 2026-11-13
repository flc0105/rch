"""Python text output capture without redirecting other execution threads."""
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar

_targets = ContextVar('python_output_targets', default=None)
_lock = threading.RLock()
_users = 0
_original = None
_proxies = None


class _ContextStream:
    def __init__(self, original, index):
        self.original = original
        self.index = index

    def _target(self):
        targets = _targets.get()
        return targets[self.index] if targets is not None else self.original

    def write(self, text):
        return self._target().write(text)

    def flush(self):
        return self._target().flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


@contextmanager
def capture_output(stdout, stderr):
    """Temporarily route only this context; nested calls restore their parent."""
    global _users, _original, _proxies
    with _lock:
        if not _users:
            _original = (sys.stdout, sys.stderr)
            _proxies = tuple(_ContextStream(stream, index) for index, stream in enumerate(_original))
            sys.stdout, sys.stderr = _proxies
        _users += 1
    token = _targets.set((stdout, stderr))
    try:
        yield
    finally:
        _targets.reset(token)
        with _lock:
            _users -= 1
            if not _users:
                # Do not overwrite a stream explicitly replaced by user code.
                if sys.stdout is _proxies[0]:
                    sys.stdout = _original[0]
                if sys.stderr is _proxies[1]:
                    sys.stderr = _original[1]
                _original = _proxies = None


class StreamOutput:
    """Emit complete lines, explicit flushes and bounded long-line chunks."""
    CHUNK_SIZE = 16384

    def __init__(self, emit):
        self.emit = emit
        self.pending = ''

    def write(self, text):
        self.pending += text
        while self.pending:
            newline = self.pending.find('\n')
            if newline >= 0 and newline < self.CHUNK_SIZE:
                end = newline + 1
            elif len(self.pending) >= self.CHUNK_SIZE:
                end = self.CHUNK_SIZE
            else:
                break
            chunk, self.pending = self.pending[:end], self.pending[end:]
            self.emit(chunk.rstrip('\r\n') if chunk.endswith('\n') else chunk)
        return len(text)

    def flush(self):
        if self.pending:
            chunk, self.pending = self.pending, ''
            self.emit(chunk)
