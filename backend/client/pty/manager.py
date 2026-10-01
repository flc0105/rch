import base64
import os
import threading

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

    def __init__(self, connection):
        self.connection = connection
        self._lock = threading.RLock()
        self._sessions = {}
        self._unix_backend = None
        self._windows_backend = None

    def open_session(self, pty_session_id: str, shell: str = '', cwd: str = '', cols: int = 120, rows: int = 32):
        with self._lock:
            if pty_session_id in self._sessions:
                self.close_session(pty_session_id)

        if os.name == 'nt':
            return self.windows_backend.open_session(
                pty_session_id,
                shell=shell,
                cwd=cwd,
                cols=cols,
                rows=rows,
            )

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
            pty_session_ids = list(self._sessions.keys())

        for pty_session_id in pty_session_ids:
            self.close_session(pty_session_id, notify=notify)

    def register_session(self, session):
        with self._lock:
            self._sessions[session.pty_session_id] = session

    def get_session(self, pty_session_id: str):
        with self._lock:
            return self._sessions.get(str(pty_session_id))

    def finalize_session(self, pty_session_id: str, exit_code: int = 0, notify: bool = True):
        with self._lock:
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

    def send_opened(self, pty_session_id: str, shell: str = ''):
        self.connection.send({
            'type': MSG_TYPE_PTY_OPENED,
            'pty_session_id': pty_session_id,
            'shell': str(shell or ''),
        })

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