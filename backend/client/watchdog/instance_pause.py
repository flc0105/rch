"""Optional pause/resume support for a single Python Client process.

Only the Remote HTTP watchdog uses this IPC channel. Local watchdog recovery and
its heartbeat remain independent of the Client connection pause state.
"""
import atexit
import os
import tempfile
import threading
import uuid
from multiprocessing.connection import Client as IPCClient
from multiprocessing.connection import Listener


class InstancePauseControl:
    def __init__(self):
        self.requested = False
        self.paused = False
        self.wake = threading.Event()
        self.listener = None
        self._endpoint = ('', '')

    def listen(self):
        if self.listener is not None:
            return self._endpoint
        family = 'AF_PIPE' if os.name == 'nt' else 'AF_UNIX'
        address = (rf'\\.\pipe\rch-resume-{uuid.uuid4().hex}' if family == 'AF_PIPE'
                   else os.path.join(tempfile.gettempdir(), f'rch-resume-{uuid.uuid4().hex}.sock'))
        authkey = os.urandom(24)
        listener = Listener(address=address, family=family, authkey=authkey)
        if family == 'AF_UNIX':
            os.chmod(address, 0o600)
        self.listener = listener
        self._endpoint = (address, authkey.hex())
        atexit.register(listener.close)

        def serve():
            while True:
                try:
                    conn = listener.accept()
                    try:
                        action = conn.recv()
                        if action == 'status':
                            conn.send(self.paused)
                        elif action == 'resume':
                            accepted = self.paused
                            if accepted:
                                self.wake.set()
                            conn.send(accepted)
                    finally:
                        conn.close()
                except (EOFError, OSError):
                    break
                except Exception:
                    # A failed probe must not terminate the per-process listener.
                    continue

        threading.Thread(target=serve, name='ClientRemoteResume', daemon=True).start()
        return self._endpoint

    def request(self, guard):
        if guard is None or not guard.is_remote_watchdog_available() or self.listener is None:
            return False
        self.wake.clear()
        self.requested = True
        return True

    def consume(self):
        result = self.requested
        self.requested = False
        return result

    def disconnect_and_wait(self, server, reset_connection):
        """Send the normal session-end reason before closing the command socket."""
        self.paused = True
        try:
            server.report_session_end('client_paused', command='pause_instance')
            try:
                server.shutdown()
            except OSError:
                pass
            reset_connection()
            self.wake.wait()
        finally:
            self.paused = False
            self.wake.clear()


def _ipc(address, authkey, action, timeout):
    if not address or not authkey:
        return None
    family = 'AF_PIPE' if os.name == 'nt' else 'AF_UNIX'
    try:
        conn = IPCClient(address, family=family, authkey=bytes.fromhex(authkey))
        try:
            conn.send(action)
            if not conn.poll(timeout):
                return None
            answer = conn.recv()
            return answer if isinstance(answer, bool) else None
        finally:
            conn.close()
    except (OSError, EOFError, ValueError, ConnectionError):
        return None


def query_client_pause_state(address, authkey):
    return _ipc(address, authkey, 'status', 1)


def wake_client(address, authkey):
    return _ipc(address, authkey, 'resume', 2) is True
