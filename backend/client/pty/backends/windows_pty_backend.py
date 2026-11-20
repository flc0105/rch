"""Windows PTY orchestration; native calls run in a helper process."""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from client.pty.session import PtySession
from core.utils.logger import logger


class _Worker:
    """Nonblocking control channel to a single Windows PTY helper process."""

    def __init__(self, process):
        self.process = process
        self.commands = queue.Queue(maxsize=256)
        self.writer = threading.Thread(target=self._write_loop, daemon=True)
        self.writer.start()
        self._closing = False
        self._lock = threading.Lock()

    def _write_loop(self):
        try:
            while True:
                command = self.commands.get()
                if command is None:
                    break
                self.process.stdin.write((json.dumps(command, ensure_ascii=True) + '\n').encode('ascii'))
                self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def send(self, command):
        with self._lock:
            if self._closing or self.process.poll() is not None:
                return False
            try:
                self.commands.put_nowait(command)
            except queue.Full:
                raise RuntimeError('Windows PTY input buffer is full') from None
            return True

    def close(self):
        with self._lock:
            if self._closing:
                return
            self._closing = True
            try:
                self.commands.put_nowait({'op': 'close'})
            except queue.Full:
                self.terminate()
                return
            try:
                self.commands.put_nowait(None)
            except queue.Full:
                pass
        threading.Thread(target=self._finish_close, daemon=True).start()

    def _finish_close(self):
        try:
            self.process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            self.terminate()
        finally:
            self._close_streams()

    def terminate(self):
        if self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass

    def _close_streams(self):
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except OSError:
                pass


class WindowsPtyBackend:
    """One helper process per Windows PTY session isolates native calls."""

    def __init__(self, manager):
        self.manager = manager
        self._lock = threading.Lock()
        self._pending = {}

    def _worker_path(self):
        return Path(__file__).with_name('windows_pty_worker.py')

    def _launch(self):
        return subprocess.Popen(
            [sys.executable, '-u', str(self._worker_path())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )

    def _register_pending(self, token, worker):
        with self._lock:
            self._pending[token] = worker

    def _take_pending(self, token):
        with self._lock:
            return self._pending.pop(token, None)

    def cancel_pending(self, token):
        worker = self._take_pending(token)
        if worker:
            worker.terminate()

    NATIVE_START_TIMEOUT_SECONDS = 12.0
    NATIVE_START_ATTEMPTS = 2

    def open_session(self, pty_session_id: str, shell: str = '', cwd: str = '', cols: int = 120,
                     rows: int = 32, *, opening=None):
        """Called in manager's startup thread; native calls occur only in child processes."""
        worker = None
        try:
            if opening is not None and not self.manager.is_windows_opening(pty_session_id, opening):
                return None
            application, command = self.build_windows_command(shell)
            last_failure = ''
            for attempt in range(1, self.NATIVE_START_ATTEMPTS + 1):
                if opening is not None and not self.manager.is_windows_opening(pty_session_id, opening):
                    return None
                process = self._launch()
                worker = _Worker(process)
                if opening is not None:
                    self._register_pending(opening, worker)
                    if not self.manager.is_windows_opening(pty_session_id, opening):
                        self.cancel_pending(opening)
                        return None
                if not worker.send({
                    'op': 'open', 'application': application, 'command': command,
                    'cwd': cwd if cwd and os.path.isdir(cwd) else '',
                    'cols': max(20, int(cols or 120)), 'rows': max(5, int(rows or 32)),
                }):
                    raise RuntimeError('Cannot send Windows PTY request to helper process')

                timed_out = threading.Event()
                stage = 'starting helper'

                def expire(target=worker, flag=timed_out):
                    # Terminating the *process*, rather than a Python thread,
                    # works even when the child is stuck in pywinpty holding its GIL.
                    if target.process.poll() is None:
                        flag.set()
                        target.terminate()

                timer = threading.Timer(self.NATIVE_START_TIMEOUT_SECONDS, expire)
                timer.daemon = True
                timer.start()
                message = None
                try:
                    while True:
                        line = process.stdout.readline()
                        if not line:
                            break
                        message = json.loads(line)
                        event = message.get('event')
                        if event == 'stage':
                            stage = str(message.get('value') or '')
                            if opening is not None:
                                self.manager.set_windows_open_stage(pty_session_id, opening, stage)
                            logger.info('Windows PTY startup: session=%s attempt=%s stage=%s',
                                        pty_session_id, attempt, stage)
                        elif event == 'error':
                            last_failure = message.get('message') or 'Windows PTY startup failed'
                            break
                        elif event == 'opened':
                            break
                finally:
                    timer.cancel()

                if message is not None and message.get('event') == 'opened' and not timed_out.is_set():
                    backend_name = message['backend']
                    session = PtySession(
                        pty_session_id=pty_session_id, backend=self, cols=cols, rows=rows,
                        pty=worker, pid=int(message.get('pid') or 0), command=command,
                    )
                    self._take_pending(opening)
                    if opening is None:
                        self.manager.register_session(session)
                        self.manager.send_opened(pty_session_id, shell=command, backend=backend_name)
                    elif not self.manager.finish_windows_open(session, opening, command, backend=backend_name):
                        worker.close()
                        return None
                    threading.Thread(target=self.reader_loop, args=(session, worker), daemon=True).start()
                    return True

                if timed_out.is_set():
                    last_failure = f'Windows PTY startup stuck at {stage} (attempt {attempt}/{self.NATIVE_START_ATTEMPTS})'
                elif not last_failure:
                    last_failure = f'Windows PTY helper exited before opening (code {process.poll()})'
                worker.terminate()
                worker._close_streams()
                self._take_pending(opening)
                if not timed_out.is_set() or attempt == self.NATIVE_START_ATTEMPTS:
                    break
                logger.warning('Windows PTY cold startup timed out; retrying in a new process: %s', last_failure)

            if opening is None:
                self.manager.send_error(pty_session_id, last_failure)
            else:
                self.manager.fail_windows_open(pty_session_id, opening, last_failure)
            return None
        except Exception as exc:
            self._take_pending(opening)
            if worker:
                worker.terminate()
            if opening is None:
                self.manager.send_error(pty_session_id, str(exc))
            else:
                self.manager.fail_windows_open(pty_session_id, opening, str(exc))
            return None

    def write_input(self, session: PtySession, raw: bytes):
        if session.pty and raw:
            session.pty.send({'op': 'input', 'text': raw.decode('utf-8', errors='replace')})

    def resize_session(self, session: PtySession, cols: int, rows: int):
        if session.pty:
            session.pty.send({'op': 'resize', 'cols': cols, 'rows': rows})

    def close_session(self, session: PtySession) -> int:
        if session.pty:
            session.pty.close()
            session.pty = None
        return 0

    def cleanup_session(self, session: PtySession):
        if session.pty:
            session.pty.close()
            session.pty = None

    def reader_loop(self, session: PtySession, worker: _Worker):
        pty_session_id = session.pty_session_id
        exit_code = 0
        try:
            for line in worker.process.stdout:
                if session.closed or self.manager.get_session(pty_session_id) is not session:
                    break
                message = json.loads(line)
                event = message.get('event')
                if event == 'output':
                    self.manager.send_output(
                        pty_session_id, message.get('text', '').encode('utf-8', errors='replace')
                    )
                elif event == 'closed':
                    exit_code = int(message.get('exit_code') or 0)
                    break
                elif event == 'error':
                    self.manager.send_error(pty_session_id, message.get('message', 'PTY error'))
        except (OSError, ValueError):
            logger.exception('Windows PTY helper output failed: %s', pty_session_id)
        finally:
            worker.close()
            if self.manager.get_session(pty_session_id) is session:
                self.manager.finalize_session(
                    pty_session_id, exit_code=exit_code, expected_session=session
                )

    def build_windows_command(self, shell: str):
        shell = str(shell or '').strip()
        if shell:
            return self.parse_windows_command(shell)
        for candidate in ('cmd.exe', 'pwsh.exe', 'powershell.exe'):
            path = self.which_windows(candidate)
            if path:
                return path, f'"{path}"' if candidate == 'cmd.exe' else f'"{path}" -NoLogo'
        return r'C:\Windows\System32\cmd.exe', r'"C:\Windows\System32\cmd.exe"'

    def parse_windows_command(self, shell: str):
        if shell.startswith('"'):
            end = shell.find('"', 1)
            if end > 0:
                executable = shell[1:end]
                rest = shell[end + 1:].strip()
                return executable, f'"{executable}" {rest}'.strip()
        parts = shell.split(None, 1)
        executable = parts[0]
        if not os.path.isabs(executable):
            executable = self.which_windows(executable) or executable
        rest = parts[1] if len(parts) > 1 else ''
        return executable, f'"{executable}" {rest}'.strip()

    def which_windows(self, executable: str):
        if os.path.isabs(executable) and os.path.isfile(executable):
            return executable
        extensions = os.environ.get('PATHEXT', '.EXE;.BAT;.CMD').split(';')
        names = [executable]
        if not any(executable.lower().endswith(ext.lower()) for ext in extensions):
            names.extend(executable + ext for ext in extensions)
        for folder in os.environ.get('PATH', '').split(os.pathsep):
            folder = folder.strip().strip('"')
            if folder:
                for name in names:
                    path = os.path.join(folder, name)
                    if os.path.isfile(path):
                        return path
        return None
