import base64
import os
import threading

from core.utils.logger import logger

from client.pty.backends.unix_pty_backend import UnixPtyBackend
from client.pty.backends.windows_pty_backend import WindowsPtyBackend
from core.device.local_identity import get_local_identity
from core.protocol.message_types import (
    MSG_TYPE_PTY_CLOSED,
    MSG_TYPE_PTY_ERROR,
    MSG_TYPE_PTY_OPENED,
    MSG_TYPE_PTY_OUTPUT,
)


class PtyManager:
    """
    PTY 会话管理器。

    只负责：
    - 会话生命周期
    - backend 选择
    - 输入解码
    - PTY 协议消息发送

    Unix / Windows 具体实现放到各自 backend 中。
    """

    WINDOWS_OPEN_TIMEOUT_SECONDS = 29
    WINDOWS_MAX_PENDING_STARTS = 2

    def __init__(self, connection):
        self.connection = connection
        self._lock = threading.RLock()
        self._sessions = {}
        self._unix_backend = None
        self._windows_backend = None
        self._windows_opening = {}
        # Bound concurrent helper startups to avoid exhausting Windows resources.
        self._windows_start_slots = threading.BoundedSemaphore(self.WINDOWS_MAX_PENDING_STARTS)

    def open_session(self, pty_session_id: str, shell: str = '', cwd: str = '', cols: int = 120, rows: int = 32):
        if os.name == 'nt':
            return self._open_windows_async(pty_session_id, shell, cwd, cols, rows)

        with self._lock:
            if pty_session_id in self._sessions:
                self.close_session(pty_session_id)

        if get_local_identity().os_alias == 'ios':
            self.send_error(pty_session_id, 'iOS is not supported')
            return False

        return self.unix_backend.open_session(
            pty_session_id,
            shell=shell,
            cwd=cwd,
            cols=cols,
            rows=rows,
        )

    def _open_windows_async(self, pty_session_id, shell, cwd, cols, rows):
        if not pty_session_id:
            self.send_error(pty_session_id, 'Missing PTY session ID')
            return False
        # Closing an old session also cancels a pending open with this ID.
        self.close_session(pty_session_id, notify=False)
        if not self._windows_start_slots.acquire(blocking=False):
            self.send_error(pty_session_id, 'Windows PTY startup is busy; retry shortly')
            return False

        token = object()
        timer = threading.Timer(
            self.WINDOWS_OPEN_TIMEOUT_SECONDS, self._windows_open_timeout,
            args=(pty_session_id, token),
        )
        timer.daemon = True
        with self._lock:
            self._windows_opening[pty_session_id] = (token, timer, 'helper startup')
        worker_started = False
        try:
            worker = threading.Thread(
                target=self._run_windows_open,
                args=(pty_session_id, token, shell, cwd, cols, rows),
                name='WindowsPtyOpen', daemon=True,
            )
            timer.start()
            worker.start()
            worker_started = True
        except Exception as exc:
            self.fail_windows_open(pty_session_id, token, str(exc))
            if not worker_started:
                self._windows_start_slots.release()
            return False
        return True

    def _run_windows_open(self, pty_session_id, token, shell, cwd, cols, rows):
        try:
            self.windows_backend.open_session(
                pty_session_id, shell=shell, cwd=cwd, cols=cols, rows=rows,
                opening=token,
            )
            # A backend must either open a session or report its own error.
            self.fail_windows_open(pty_session_id, token, 'Windows PTY failed to open')
        except Exception as exc:
            logger.exception('Windows PTY startup failed: %s', pty_session_id)
            self.fail_windows_open(pty_session_id, token, str(exc))
        finally:
            self._windows_start_slots.release()

    def _windows_open_timeout(self, pty_session_id, token):
        with self._lock:
            pending = self._windows_opening.get(pty_session_id)
            if pending is None or pending[0] is not token:
                return
            stage = pending[2]
        logger.warning('Windows PTY opening exceeded %ss at %s: %s',
                       self.WINDOWS_OPEN_TIMEOUT_SECONDS, stage, pty_session_id)
        self.fail_windows_open(
            pty_session_id, token,
            f'Windows PTY startup timed out after {self.WINDOWS_OPEN_TIMEOUT_SECONDS}s'
            f' (stage: {stage})',
        )

    def set_windows_open_stage(self, pty_session_id, token, stage):
        with self._lock:
            pending = self._windows_opening.get(pty_session_id)
            if pending is None or pending[0] is not token:
                return False
            self._windows_opening[pty_session_id] = (token, pending[1], stage)
            return True

    def is_windows_opening(self, pty_session_id, token):
        with self._lock:
            pending = self._windows_opening.get(pty_session_id)
            return pending is not None and pending[0] is token

    def fail_windows_open(self, pty_session_id, token, message):
        with self._lock:
            if not self.is_windows_opening(pty_session_id, token):
                return False
            _, timer, _ = self._windows_opening.pop(pty_session_id)
            timer.cancel()
            self.send_error(pty_session_id, message)
        self.windows_backend.cancel_pending(token)
        return True

    def finish_windows_open(self, session, token, shell, *, backend):
        with self._lock:
            if not self.is_windows_opening(session.pty_session_id, token):
                return False
            _, timer, _ = self._windows_opening.pop(session.pty_session_id)
            timer.cancel()
            self._sessions[session.pty_session_id] = session
            try:
                self.send_opened(session.pty_session_id, shell=shell, backend=backend)
            except Exception:
                self._sessions.pop(session.pty_session_id, None)
                raise
            return True

    def _cancel_windows_open(self, pty_session_id):
        with self._lock:
            pending = self._windows_opening.pop(pty_session_id, None)
            if pending:
                pending[1].cancel()
        if pending:
            self.windows_backend.cancel_pending(pending[0])
        return pending is not None

    def write_input(self, pty_session_id: str, data: str):
        session = self.get_session(pty_session_id)
        if not session:
            return None

        try:
            raw = base64.b64decode(str(data or '').encode(), validate=False)
        except Exception:
            raw = str(data or '').encode('utf-8', errors='replace')

        try:
            return session.backend.write_input(session, raw)
        except Exception as e:
            self.send_error(pty_session_id, str(e))
            return None

    def resize_session(self, pty_session_id: str, cols: int, rows: int):
        session = self.get_session(pty_session_id)
        if not session:
            return None

        cols = max(20, int(cols or session.cols or 120))
        rows = max(5, int(rows or session.rows or 32))
        session.cols = cols
        session.rows = rows

        try:
            return session.backend.resize_session(session, cols, rows)
        except Exception:
            return None

    def close_session(self, pty_session_id: str, notify: bool = True):
        self._cancel_windows_open(pty_session_id)
        session = self.get_session(pty_session_id)
        if not session:
            return None

        with self._lock:
            session.closed = True

        try:
            exit_code = session.backend.close_session(session)
        except Exception:
            exit_code = 0

        self.finalize_session(pty_session_id, exit_code=exit_code, notify=notify)
        return None

    def close_all_sessions(self, notify: bool = True):
        with self._lock:
            pty_session_ids = list(set(self._sessions) | set(self._windows_opening))

        for pty_session_id in pty_session_ids:
            self.close_session(pty_session_id, notify=notify)

    def register_session(self, session):
        with self._lock:
            self._sessions[session.pty_session_id] = session

    def get_session(self, pty_session_id: str):
        with self._lock:
            return self._sessions.get(str(pty_session_id))

    def finalize_session(self, pty_session_id: str, exit_code: int = 0, notify: bool = True, expected_session=None):
        with self._lock:
            session = self._sessions.get(str(pty_session_id))
            if expected_session is not None and session is not expected_session:
                return None
            session = self._sessions.pop(str(pty_session_id), None)

        if not session:
            return None

        try:
            session.backend.cleanup_session(session)
        except Exception:
            pass

        if notify:
            self.send_closed(pty_session_id, exit_code=exit_code)

        return None

    def send_opened(self, pty_session_id: str, shell: str = '', *, backend: str = ''):
        payload = {
            'type': MSG_TYPE_PTY_OPENED,
            'pty_session_id': pty_session_id,
            'shell': str(shell or ''),
        }
        if backend:
            payload['backend'] = backend
        self.connection.send(payload)

    def send_output(self, pty_session_id: str, data: bytes):
        self.connection.send({
            'type': MSG_TYPE_PTY_OUTPUT,
            'pty_session_id': pty_session_id,
            'data': base64.b64encode(data or b'').decode(),
        })

    def send_closed(self, pty_session_id: str, exit_code: int = 0):
        self.connection.send({
            'type': MSG_TYPE_PTY_CLOSED,
            'pty_session_id': pty_session_id,
            'exit_code': int(exit_code or 0),
        })

    def send_error(self, pty_session_id: str, message: str):
        self.connection.send({
            'type': MSG_TYPE_PTY_ERROR,
            'pty_session_id': pty_session_id,
            'message': str(message or 'PTY error'),
        })

    @property
    def unix_backend(self):
        if self._unix_backend is None:
            self._unix_backend = UnixPtyBackend(self)
        return self._unix_backend

    @property
    def windows_backend(self):
        if self._windows_backend is None:
            self._windows_backend = WindowsPtyBackend(self)
        return self._windows_backend
