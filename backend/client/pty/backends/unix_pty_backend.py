import errno
import os
import select
import time
import shutil
import signal
import struct
import threading

if os.name != 'nt':
    import termios
else:
    termios = None

from client.pty.session import PtySession


class UnixPtyBackend:
    """
    Unix PTY 后端。
    """

    def __init__(self, manager):
        self.manager = manager

    def open_session(self, pty_session_id: str, shell: str = '', cwd: str = '', cols: int = 120, rows: int = 32):
        try:
            shell_path = self.resolve_shell_path(shell)
        except Exception as e:
            self.manager.send_error(pty_session_id, str(e))
            return None

        # 用 close-on-exec pipe 确认子进程已经真正 exec 到目标 shell。
        exec_read_fd, exec_write_fd = os.pipe()
        os.set_inheritable(exec_write_fd, False)

        pid, master_fd = os.forkpty()
        if pid == 0:
            try:
                os.close(exec_read_fd)

                try:
                    if cwd:
                        os.chdir(cwd)
                except Exception:
                    pass

                env = os.environ.copy()
                env.setdefault('TERM', 'xterm-256color')
                env.setdefault('COLORTERM', 'truecolor')

                try:
                    os.execve(shell_path, self.shell_arguments(shell_path), env)
                except Exception as e:
                    try:
                        os.write(exec_write_fd, str(e).encode('utf-8', errors='replace'))
                    except Exception:
                        pass
                    os._exit(127)
            except Exception as e:
                try:
                    os.write(exec_write_fd, str(e).encode('utf-8', errors='replace'))
                except Exception:
                    pass
                os._exit(127)

        os.close(exec_write_fd)

        try:
            exec_error = os.read(exec_read_fd, 4096)
        finally:
            os.close(exec_read_fd)

        if exec_error:
            try:
                os.close(master_fd)
            except Exception:
                pass
            try:
                os.waitpid(pid, 0)
            except Exception:
                pass

            self.manager.send_error(
                pty_session_id,
                exec_error.decode('utf-8', errors='replace') or f'Failed to start shell: {shell_path}',
            )
            return None

        self.resize_fd(master_fd, cols, rows)
        session = PtySession(
            pty_session_id=pty_session_id,
            backend=self,
            pid=pid,
            master_fd=master_fd,
            cols=cols,
            rows=rows,
            closed=False,
        )
        self.manager.register_session(session)
        self.manager.send_opened(pty_session_id, shell=shell_path)

        threading.Thread(target=self.reader_loop, args=(pty_session_id,), daemon=True).start()
        return True

    @staticmethod
    def shell_arguments(shell_path: str) -> list[str]:
        # Login profiles initialize PATH (notably Homebrew on macOS), while
        # interactive startup still loads aliases, prompts and shell options.
        if os.path.basename(shell_path) in ('zsh', 'bash'):
            return [shell_path, '-l', '-i']
        return [shell_path, '-i']

    def resolve_shell_path(self, shell: str = '') -> str:
        requested = str(shell or '').strip()

        if requested:
            candidate = requested if os.path.isabs(requested) else shutil.which(requested)
            if not candidate:
                raise FileNotFoundError(f'Shell not found: {requested}')
            if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
                raise FileNotFoundError(f'Shell is not executable: {candidate}')
            return candidate

        candidates = [
            str(os.environ.get('SHELL') or '').strip(),
            '/bin/zsh',
            '/bin/bash',
        ]
        for candidate in candidates:
            if not candidate:
                continue
            resolved = candidate if os.path.isabs(candidate) else shutil.which(candidate)
            if resolved and os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                return resolved

        raise FileNotFoundError('No supported shell found')

    def write_input(self, session: PtySession, raw: bytes):
        if session.master_fd is None:
            return None
        return os.write(session.master_fd, raw)

    def resize_session(self, session: PtySession, cols: int, rows: int):
        if session.master_fd is None:
            return None
        return self.resize_fd(session.master_fd, cols, rows)

    def close_session(self, session: PtySession) -> int:
        try:
            os.kill(session.pid, signal.SIGTERM)
        except Exception:
            pass
        return 0

    def cleanup_session(self, session: PtySession):
        if session.master_fd is None:
            return None
        try:
            os.close(session.master_fd)
        except Exception:
            pass
        finally:
            session.master_fd = None
        return None

    def reader_loop(self, pty_session_id: str):
        session = self.manager.get_session(pty_session_id)
        if not session:
            return

        master_fd = session.master_fd
        pid = session.pid
        exit_code = 0
        reaped = False
        drain_deadline = None

        if master_fd is None:
            self.manager.finalize_session(pty_session_id, exit_code=exit_code)
            return

        def reap_child():
            nonlocal reaped, exit_code, drain_deadline
            if reaped:
                return
            try:
                waited_pid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                reaped = True
                return
            if waited_pid != pid:
                return
            reaped = True
            if os.WIFEXITED(status):
                exit_code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                exit_code = 128 + os.WTERMSIG(status)
            # Drain output remaining in the master after shell exit, but don't
            # hang indefinitely if a background child retained the slave FD.
            drain_deadline = time.monotonic() + 0.5

        try:
            while True:
                current = self.manager.get_session(pty_session_id)
                if not current or current.closed:
                    break

                timeout = 0.2 if drain_deadline is None else min(
                    0.2, max(0.0, drain_deadline - time.monotonic()))
                readable, _, _ = select.select([master_fd], [], [], timeout)
                if master_fd in readable:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError as exc:
                        # Linux PTY masters signal ordinary slave EOF with EIO.
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    self.manager.send_output(pty_session_id, chunk)

                reap_child()
                if drain_deadline is not None and time.monotonic() >= drain_deadline:
                    break
        except Exception as exc:
            if self.manager.get_session(pty_session_id):
                self.manager.send_error(pty_session_id, str(exc))
        finally:
            reap_child()
            self.manager.finalize_session(pty_session_id, exit_code=exit_code)

    def resize_fd(self, master_fd: int, cols: int, rows: int):
        if termios is None:
            return None

        winsz = struct.pack('HHHH', int(rows), int(cols), 0, 0)
        fcntl = __import__('fcntl')
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsz)
        return None