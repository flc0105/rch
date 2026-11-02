"""Unix operator-terminal bridge for an existing RCH remote PTY session.

The local terminal handles VT/ANSI rendering. RCH owns the remote PTY and its
lifecycle; this module transports keystrokes and output without interpreting
remote shell commands or changing the regular RCH command-execution path.
"""

import base64
import json
import os
import select
import shlex
import sys
import termios
import time
import tty
from urllib.parse import quote, urlsplit, urlunsplit


class RchPtyError(Exception):
    """Recoverable PTY failure; the caller can return to the RCH CLI prompt."""


class UnixTerminal:
    """Owns the raw-mode lifetime and restores the original terminal state."""

    def __init__(self, input_fd=None, output_fd=None):
        self.input_fd = sys.stdin.fileno() if input_fd is None else input_fd
        self.output_fd = sys.stdout.fileno() if output_fd is None else output_fd
        if not os.isatty(self.input_fd) or not os.isatty(self.output_fd):
            raise RchPtyError('PTY needs an interactive system terminal (stdin and stdout must be TTYs)')
        self._saved = None

    def size(self):
        try:
            size = os.get_terminal_size(self.output_fd)
        except OSError:
            size = os.get_terminal_size(self.input_fd)
        return max(20, size.columns), max(5, size.lines)

    def __enter__(self):
        self._saved = termios.tcgetattr(self.input_fd)
        try:
            tty.setraw(self.input_fd)
        except BaseException:
            termios.tcsetattr(self.input_fd, termios.TCSADRAIN, self._saved)
            self._saved = None
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._saved is not None:
            try:
                # A detached Vim may not get to emit its final alternate-screen
                # reset before the PTY socket closes. Restore our local display.
                self.write(b'\x1b[?25h\x1b[?1049l\x1b[0m')
            finally:
                termios.tcsetattr(self.input_fd, termios.TCSADRAIN, self._saved)
                self._saved = None

    def read_ready(self):
        ready, _, _ = select.select([self.input_fd], [], [], 0)
        return os.read(self.input_fd, 4096) if ready else None

    def write(self, data):
        view = memoryview(data)
        while view:
            sent = os.write(self.output_fd, view)
            if sent <= 0:
                raise RchPtyError('Local terminal output was closed')
            view = view[sent:]


class PtyBridge:
    """One foreground PTY session on the synchronous RCH PTY WebSocket."""

    def __init__(self, terminal):
        self.terminal = terminal
        self.last_seq = 0
        self.status = 'opening'
        self.error = ''
        self.escape_pending = False

    def receive(self, raw):
        if not isinstance(raw, str):
            return
        try:
            item = json.loads(raw)
        except ValueError:
            return
        if not isinstance(item, dict) or item.get('type') not in ('output', 'status'):
            return
        for chunk in item.get('chunks') or []:
            if not isinstance(chunk, dict):
                continue
            try:
                seq = int(chunk.get('seq') or 0)
            except (TypeError, ValueError):
                continue
            if seq <= self.last_seq:
                continue
            self.last_seq = seq
            self.terminal.write(str(chunk.get('text') or '').encode('utf-8'))
        self.status = str(item.get('status') or self.status)
        self.error = str(item.get('error') or self.error)

    def forward_keys(self, data):
        """Ctrl+] q closes locally, Ctrl+] ] sends a literal Ctrl+] remotely."""
        forwarded = bytearray()
        quit_requested = False
        for key in data:
            if self.escape_pending:
                self.escape_pending = False
                if key == ord('q'):
                    quit_requested = True
                    break
                if key == ord(']'):
                    forwarded.append(0x1d)
                else:
                    forwarded.extend((0x1d, key))
            elif key == 0x1d:
                self.escape_pending = True
            else:
                forwarded.append(key)
        return bytes(forwarded), quit_requested


def parse_pty_options(raw):
    """Return (remote shell, optional width cap) for the local :pty command."""
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise RchPtyError(f'Invalid PTY arguments: {exc}') from exc
    shell = ''
    cols_limit = None
    index = 0
    while index < len(tokens):
        arg = tokens[index]
        if arg == '--cols' or arg.startswith('--cols='):
            if cols_limit is not None:
                raise RchPtyError('--cols specified twice')
            if arg == '--cols':
                index += 1
                value = tokens[index] if index < len(tokens) else ''
            else:
                value = arg.partition('=')[2]
            if not value.isdecimal() or not 20 <= int(value) <= 400:
                raise RchPtyError('--cols must be an integer between 20 and 400')
            cols_limit = int(value)
        elif arg.startswith('-') or shell:
            raise RchPtyError('Usage: :pty [shell] [--cols 20..400]')
        else:
            shell = arg
        index += 1
    return shell, cols_limit


def pty_websocket_url(event_url, ws_path):
    """Preserve a reverse-proxy prefix while using the Server-issued PTY token."""
    event = urlsplit(event_url)
    issued = urlsplit(ws_path)
    if event.scheme not in ('ws', 'wss') or not event.netloc or not event.path.endswith('/ws/events'):
        raise RchPtyError('Event WS URL must end in /ws/events to derive the PTY endpoint')
    if issued.scheme or issued.netloc or not issued.path.startswith('/ws/pty/') or not issued.query:
        raise RchPtyError('Server returned an invalid PTY WebSocket path')
    proxy_prefix = event.path[:-len('/ws/events')]
    return urlunsplit((event.scheme, event.netloc, proxy_prefix + issued.path, issued.query, ''))


def run_pty(api, client_id, event_url, shell='', *, cols_limit=None, terminal=None, connect=None, open_timeout=20):
    """Open and drive a remote PTY until shell exit, Ctrl+] q, or disconnect.

    ``api`` is the existing rchcli.RchApi; ``event_url`` is its event WS URL.
    Dependencies and Unix TTY requirements are checked before creating a session.
    """
    if os.name != 'posix' or sys.platform == 'ios':
        raise RchPtyError('Local PTY mode currently supports macOS and Linux system terminals')
    terminal = terminal if terminal is not None else UnixTerminal()
    if connect is None:
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise RchPtyError('Install websockets>=14 to use PTY mode') from exc
    try:
        cols, rows = terminal.size()
        if cols_limit is not None:
            cols = min(cols, cols_limit)
    except OSError as exc:
        raise RchPtyError(f'Cannot read local terminal size: {exc}') from exc
    result = api.request('POST', '/api/connections/' + quote(client_id, safe='') + '/pty/open', {
        'cols': cols, 'rows': rows, 'shell': shell, 'cwd': '',
    })
    if not isinstance(result, dict) or not result.get('pty_session_id'):
        raise RchPtyError('Server did not return a PTY session ID')
    session_id = str(result['pty_session_id'])
    try:
        endpoint = pty_websocket_url(event_url, result.get('ws_path') or '')
        with connect(endpoint, open_timeout=8, close_timeout=2, max_size=16 * 1024 * 1024) as ws:
            bridge = PtyBridge(terminal)
            deadline = time.monotonic() + open_timeout
            # Do not put the local keyboard into raw mode until the remote shell
            # has acknowledged startup. Output is still rendered directly.
            while bridge.status == 'opening':
                if time.monotonic() >= deadline:
                    raise RchPtyError('Remote PTY did not open in time')
                try:
                    raw = ws.recv(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
                except TimeoutError:
                    continue
                bridge.receive(raw)
            if bridge.status == 'error':
                raise RchPtyError(bridge.error or 'Remote PTY failed to open')
            if bridge.status == 'closed':
                return
            if bridge.status != 'open':
                raise RchPtyError('Unexpected PTY state: ' + bridge.status)
            last_size = (cols, rows)
            with terminal:
                while bridge.status == 'open':
                    # Polling dimensions also works on terminals without SIGWINCH.
                    next_size = terminal.size()
                    if cols_limit is not None:
                        next_size = (min(next_size[0], cols_limit), next_size[1])
                    if next_size != last_size:
                        ws.send(json.dumps({'type': 'resize', 'cols': next_size[0], 'rows': next_size[1]}))
                        last_size = next_size
                    data = terminal.read_ready()
                    if data == b'':
                        break
                    if data:
                        payload, quit_requested = bridge.forward_keys(data)
                        if payload:
                            ws.send(json.dumps({'type': 'input', 'data': base64.b64encode(payload).decode('ascii')}))
                        if quit_requested:
                            break
                    try:
                        raw = ws.recv(timeout=0.05)
                    except TimeoutError:
                        continue
                    bridge.receive(raw)
            # The remote process may have just exited or the user closed it.
            if bridge.status == 'error':
                raise RchPtyError(bridge.error or 'Remote PTY failed')
    except RchPtyError:
        raise
    except Exception as exc:
        raise RchPtyError(f'PTY transport failed: {exc}') from exc
    finally:
        # Closing the PTY WS already closes the Server session. Explicit HTTP
        # close also handles failed WS handshakes and keyboard interrupts.
        try:
            api.request('POST', '/api/pty/' + quote(session_id, safe='') + '/close', {})
        except Exception:
            pass
