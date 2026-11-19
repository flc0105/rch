"""Isolated Windows ConPTY process. Standard input/output carry newline-delimited JSON.

Keep the pywinpty native calls outside the network Client process: some
ConPTY bindings execute while holding the Python GIL.
"""
import ctypes
import json
import os
import signal
import sys
import threading
import time
from importlib import metadata


_output_lock = threading.Lock()


def _send(event, **fields):
    payload = (json.dumps({'event': event, **fields}, ensure_ascii=True) + '\n').encode('ascii')
    with _output_lock:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()


def _version_tuple(version):
    import re
    values = [int(value) for value in re.findall(r'\d+', version)[:3]]
    return tuple((values + [0, 0, 0])[:3])


def _stop_pty(pty):
    try:
        pty.cancel_io()
    except Exception:
        pass
    pid = int(pty.pid or 0)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def _read_output(pty, stopping):
    exit_code = 0
    try:
        while not stopping.is_set():
            try:
                text = pty.read(blocking=False)
            except Exception:
                text = ''
            if text:
                _send('output', text=text)
                continue
            try:
                if not pty.isalive():
                    for _ in range(20):
                        try:
                            tail = pty.read(blocking=False)
                        except Exception:
                            tail = ''
                        if not tail:
                            break
                        _send('output', text=tail)
                    exit_code = int(pty.get_exitstatus() or 0)
                    break
            except Exception:
                break
            time.sleep(0.02)
    except (BrokenPipeError, OSError):
        pass
    finally:
        stopping.set()
        try:
            _send('closed', exit_code=exit_code)
        except (BrokenPipeError, OSError):
            pass
        # The main thread may be blocked reading control stdin. The child has
        # exited, so finish this disposable helper without waiting for input.
        os._exit(0)


def run():
    pty = None
    stopping = threading.Event()
    try:
        try:
            version = metadata.version('pywinpty')
            if _version_tuple(version) < (3, 0, 5):
                raise RuntimeError(f'pywinpty 3.0.5+ is required; installed {version}. Install it in the Client Python environment.')
            from winpty import Backend, PTY
        except (ImportError, metadata.PackageNotFoundError) as error:
            raise RuntimeError('pywinpty 3.0.5+ is required in the Client Python environment') from error

        request = json.loads(sys.stdin.buffer.readline())
        if request.get('op') != 'open':
            raise ValueError('Missing PTY open request')
        _send('stage', value='ConPTY initialization')
        pty = PTY(int(request['cols']), int(request['rows']), backend=Backend.ConPTY)
        _send('stage', value='shell spawn')

        # The Ctrl+C inheritance workaround is limited to this disposable helper
        # process, never the main Client process or its other PTY sessions.
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        handler = kernel32.SetConsoleCtrlHandler
        handler.argtypes = [ctypes.c_void_p, ctypes.c_int]
        handler.restype = ctypes.c_int
        if not handler(None, False):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ok = pty.spawn(
                request['application'],
                cmdline=request['command'],
                cwd=request.get('cwd') or None,
                env=None,
            )
        finally:
            handler(None, True)
        if ok is False:
            raise RuntimeError('ConPTY spawn failed')
        _send('opened', pid=int(pty.pid or 0))

        reader = threading.Thread(target=_read_output, args=(pty, stopping), daemon=True)
        reader.start()
        for line in sys.stdin.buffer:
            if stopping.is_set():
                break
            message = json.loads(line)
            op = message.get('op')
            if op == 'input':
                pty.write(message.get('text', ''))
            elif op == 'resize':
                pty.set_size(int(message['cols']), int(message['rows']))
            elif op == 'close':
                break
        stopping.set()
    except Exception as error:
        try:
            _send('error', message=f'{type(error).__name__}: {error}')
        except (BrokenPipeError, OSError):
            pass
    finally:
        stopping.set()
        if pty is not None:
            _stop_pty(pty)


if __name__ == '__main__':
    run()
