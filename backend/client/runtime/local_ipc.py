"""Authenticated, process-local command delivery for Client helper processes.

The listener is bound to a private local endpoint; only the watchdog child is
handed the endpoint and authentication key through its process environment.
"""

import os
import secrets
import shutil
import tempfile
import threading
from multiprocessing.connection import Client, Listener


IPC_ADDRESS_ENV = 'RCH_LOCAL_IPC_ADDRESS'
IPC_KEY_ENV = 'RCH_LOCAL_IPC_KEY'


class LocalIpcServer:
    def __init__(self):
        self.authkey = secrets.token_bytes(32)
        self._directory = None
        if os.name == 'nt':
            self.address = rf'\\.\pipe\rch-{os.getpid()}-{secrets.token_hex(8)}'
            self.family = 'AF_PIPE'
        else:
            # /tmp keeps the Unix socket name within macOS's small sun_path limit.
            self._directory = tempfile.mkdtemp(prefix='rch-ipc-', dir='/tmp')
            self.address = os.path.join(self._directory, 'control.sock')
            self.family = 'AF_UNIX'
        self._handlers = {'ipc.shutdown': lambda: None}
        self._listener = None
        self._thread = None
        self._stop = threading.Event()

    def register(self, action, handler):
        self._handlers[action] = handler

    def start(self):
        if self._listener is not None:
            return
        self._listener = Listener(self.address, family=self.family, authkey=self.authkey)
        self._thread = threading.Thread(target=self._serve, name='ClientLocalIPC', daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                listener = self._listener
                if listener is None:
                    break
                connection = listener.accept()
            except Exception:
                if self._stop.is_set():
                    break
                continue
            try:
                if not connection.poll(3):
                    continue
                message = connection.recv()
                action = message.get('action') if isinstance(message, dict) else None
                handler = self._handlers.get(action)
                if handler is None:
                    connection.send({'ok': False, 'error': 'Unknown IPC action'})
                else:
                    handler()
                    connection.send({'ok': True})
            except (OSError, EOFError):
                pass
            except Exception as exc:
                try:
                    connection.send({'ok': False, 'error': str(exc)})
                except (OSError, EOFError):
                    pass
            finally:
                connection.close()

    def child_environment(self):
        return {IPC_ADDRESS_ENV: self.address, IPC_KEY_ENV: self.authkey.hex()}

    def stop(self):
        self._stop.set()
        if self._listener is not None:
            try:
                send_local_command('ipc.shutdown', self.address, self.authkey, timeout=1)
            except (OSError, TimeoutError, RuntimeError):
                pass
            self._listener.close()
            self._listener = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        if self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)


def send_local_command(action, address=None, authkey=None, *, timeout=3):
    """Send a named command to the current Client instance and await its ACK."""
    address = address or os.environ.get(IPC_ADDRESS_ENV, '')
    authkey = authkey or bytes.fromhex(os.environ.get(IPC_KEY_ENV, ''))
    if not address or not authkey:
        raise RuntimeError('Client local IPC is unavailable')
    with Client(address, authkey=authkey) as connection:
        connection.send({'action': action})
        if not connection.poll(timeout):
            raise TimeoutError('Client local IPC response timed out')
        response = connection.recv()
    if not isinstance(response, dict) or not response.get('ok'):
        raise RuntimeError((response or {}).get('error', 'Client local IPC failed'))
    return response
