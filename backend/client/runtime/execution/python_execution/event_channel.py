"""Dedicated ordered Python subprocess output channel (text and structured events)."""
import hmac
import io
import json
import socket
import threading
from contextlib import contextmanager, redirect_stderr, redirect_stdout


class _EventTextStream(io.TextIOBase):
    def __init__(self, sender):
        self._sender = sender

    def writable(self):
        return True

    def write(self, text):
        value = str(text)
        if value:
            self._sender({'kind': 'text', 'text': value})
        return len(value)

    def flush(self):
        pass


@contextmanager
def connect_event_stream(endpoint):
    """Child attaches before running user code; all Python output stays ordered."""
    with socket.create_connection(('127.0.0.1', endpoint['port']), timeout=10) as conn:
        lock = threading.RLock()
        def send(event):
            packet = json.dumps(event, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
            with lock:
                conn.sendall(packet)
        send({'kind': 'auth', 'token': endpoint['token']})
        output = _EventTextStream(send)
        def emit_data(data, *, view=None):
            event = {'kind': 'data', 'data': data}
            if view is not None:
                event['view'] = view
            send(event)

        def emit_progress(message, *, level=None):
            event = {'kind': 'progress', 'message': message}
            if level is not None:
                event['level'] = level
            send(event)

        # Keep one authenticated ordered channel for stdout, data and progress.
        emit_data.progress = emit_progress
        with redirect_stdout(output), redirect_stderr(output):
            yield emit_data


def read_event_stream(listener, process, token, consume):
    """Parent reader; rejects unauthenticated peers and malformed event frames."""
    listener.settimeout(0.2)
    while True:
        try:
            conn, _ = listener.accept()
            break
        except socket.timeout:
            if process.poll() is not None:
                return
    with conn:
        conn.settimeout(None)
        with conn.makefile('rb') as input_stream:
            auth = json.loads(input_stream.readline())
            if not isinstance(auth, dict) or not hmac.compare_digest(str(auth.get('token') or ''), token):
                raise ValueError('Invalid Python output channel token')
            for raw in input_stream:
                event = json.loads(raw)
                if not isinstance(event, dict) or event.get('kind') not in ('text', 'data', 'progress'):
                    raise ValueError('Invalid Python output event')
                consume(event)
