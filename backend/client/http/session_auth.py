"""Current Client connection credential for HTTP requests.

Only the active Server connection sets/clears this value. subprocess_pipe
scripts receive it in their execution context, not through global state.
"""
import threading

_lock = threading.RLock()
_token = ''


def set_token(token):
    global _token
    with _lock:
        _token = str(token or '')


def get_token():
    with _lock:
        return _token


def clear_token():
    set_token('')
