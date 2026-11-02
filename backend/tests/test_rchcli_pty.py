"""Unix local terminal and live WebSocket tests for standalone RCH CLI PTY."""

import base64
import fcntl
import json
import os
import pathlib
import pty
import queue
import select
import struct
import sys
import termios
import threading
import time
import unittest

MODULE_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))
import rchcli_pty as ptycli


class FakeApi:
    def __init__(self):
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith('/pty/open'):
            return {'pty_session_id': 'session-1', 'ws_path': '/ws/pty/session-1?token=only-for-pty'}
        return {'ok': True}


class ScriptedTerminal:
    def __init__(self, inputs, *, dimensions=None):
        self.inputs = list(inputs)
        self.dimensions = list(dimensions or [(80, 24)])
        self.writes = []
        self.entries = 0
        self.exits = 0

    def size(self):
        return self.dimensions.pop(0) if len(self.dimensions) > 1 else self.dimensions[0]

    def __enter__(self):
        self.entries += 1
        return self

    def __exit__(self, *args):
        self.exits += 1

    def read_ready(self):
        if self.inputs:
            return self.inputs.pop(0)
        return None

    def write(self, data):
        self.writes.append(bytes(data))


class FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def send(self, msg):
        self.sent.append(json.loads(msg))

    def recv(self, timeout=None):
        if not self.messages:
            raise TimeoutError()
        response = self.messages.pop(0)
        if isinstance(response, BaseException):
            raise response
        return json.dumps(response)


def status(value):
    return {'type': 'status', 'status': value}


class PtyProtocolTests(unittest.TestCase):
    def test_pty_endpoint_from_event_ws_and_reverse_proxy(self):
        self.assertEqual(
            ptycli.pty_websocket_url('wss://rch.test/gateway/ws/events?tab_id=x',
                                     '/ws/pty/s?token=secret'),
            'wss://rch.test/gateway/ws/pty/s?token=secret')
        with self.assertRaises(ptycli.RchPtyError):
            ptycli.pty_websocket_url('wss://rch.test/ws/other', '/ws/pty/s?token=secret')
        with self.assertRaises(ptycli.RchPtyError):
            ptycli.pty_websocket_url('wss://rch.test/ws/events', 'https://evil/ws/pty/s?token=secret')

    def test_protocol_bytes_are_preserved_and_quit_does_not_send_escape(self):
        api = FakeApi()
        term = ScriptedTerminal([b'vim\r\x03', b'\x1d', b'q'])
        ws = FakeSocket([status('opening'),
                         {'type': 'output', 'status': 'open', 'chunks': [
                             {'seq': 1, 'text': '\x1b[?1049h\x1b[2J\rHELLO\n'}]},
                         {'type': 'output', 'status': 'open', 'chunks': [
                             {'seq': 1, 'text': 'DUPLICATE'},
                             {'seq': 2, 'text': 'Ω'}]}])
        ptycli.run_pty(api, 'client:a', 'wss://rch.test/ws/events', terminal=term,
                       connect=lambda *a, **kw: ws)
        self.assertEqual(b''.join(term.writes), b'\x1b[?1049h\x1b[2J\rHELLO\n' + 'Ω'.encode())
        self.assertEqual([base64.b64decode(x['data']) for x in ws.sent if x['type'] == 'input'],
                         [b'vim\r\x03'])
        self.assertEqual(term.entries, 1)
        self.assertEqual(term.exits, 1)
        self.assertTrue(ws.closed)
        self.assertEqual(api.calls[0][1], '/api/connections/client%3Aa/pty/open')
        self.assertEqual(api.calls[-1][1], '/api/pty/session-1/close')

    def test_literal_ctrl_bracket_and_unknown_escape_are_forwarded(self):
        bridge = ptycli.PtyBridge(ScriptedTerminal([]))
        self.assertEqual(bridge.forward_keys(b'\x1d'), (b'', False))
        self.assertEqual(bridge.forward_keys(b']\x1dx'), (b'\x1d\x1dx', False))
        self.assertEqual(bridge.forward_keys(b'\x1dq'), (b'', True))

    def test_width_override_caps_open_and_later_resize(self):
        api = FakeApi()
        term = ScriptedTerminal([None, b'\x1dq'], dimensions=[(110, 30), (80, 32)])
        ws = FakeSocket([status('open')])
        ptycli.run_pty(api, 'abc', 'ws://host/ws/events', terminal=term,
                       connect=lambda *a, **kw: ws, cols_limit=55)
        self.assertEqual(api.calls[0][2]['cols'], 55)
        self.assertIn({'type': 'resize', 'cols': 55, 'rows': 32}, ws.sent)

    def test_pty_args_shell_and_width_cap(self):
        self.assertEqual(ptycli.parse_pty_options(''), ('', None))
        self.assertEqual(ptycli.parse_pty_options('/bin/zsh'), ('/bin/zsh', None))
        self.assertEqual(ptycli.parse_pty_options('--cols 55'), ('', 55))
        self.assertEqual(ptycli.parse_pty_options('/bin/bash --cols=60'), ('/bin/bash', 60))
        for invalid in ('--cols', '--cols nope', '--cols 8', '--cols 500',
                        '--cols 60 --cols 80', '/bin/zsh extra', '--not-an-option'):
            with self.subTest(invalid=invalid), self.assertRaises(ptycli.RchPtyError):
                ptycli.parse_pty_options(invalid)

    def test_cli_routes_width_override_to_pty_only(self):
        import io
        from unittest.mock import patch
        import rchcli
        api = FakeApi()
        api.connections = lambda: [
            {'client_id': 'client-A', 'hostname': 'Mac', 'connection_state': 'online',
             'connected_at': '2026-11-01T00:00:00'}]
        commands = iter(['0', ':pty /bin/bash --cols 60', 'bg', 'quit'])
        console = rchcli.RemoteConsole(api, object(), 'tab-id', output=io.StringIO(),
                                       reader=lambda _: next(commands),
                                       ws_url='ws://host/ws/events')
        with patch('rchcli_pty.run_pty') as run:
            console.repl()
        run.assert_called_once_with(api, 'client-A', 'ws://host/ws/events',
                                    shell='/bin/bash', cols_limit=60)
        self.assertEqual(api.calls, [])

    def test_resize_and_terminal_restore_on_close(self):
        api = FakeApi()
        term = ScriptedTerminal([None, b'\x1dq'], dimensions=[(60, 20), (90, 35)])
        ws = FakeSocket([status('open')])
        ptycli.run_pty(api, 'abc', 'ws://host/ws/events', terminal=term,
                       connect=lambda *a, **kw: ws)
        self.assertIn({'type': 'resize', 'cols': 90, 'rows': 35}, ws.sent)
        self.assertEqual((term.entries, term.exits), (1, 1))

    def test_pty_open_error_and_ws_failure_close_server_session(self):
        for messages, expected in [([status('error')], 'Remote PTY failed'),
                                   ([status('opening'), ConnectionError('lost')], 'PTY transport failed')]:
            api = FakeApi()
            term = ScriptedTerminal([])
            ws = FakeSocket(messages)
            with self.subTest(messages=messages), self.assertRaisesRegex(ptycli.RchPtyError, expected):
                ptycli.run_pty(api, 'abc', 'ws://host/ws/events', terminal=term,
                               connect=lambda *a, **kw: ws)
            self.assertEqual(term.entries, 0)
            self.assertEqual(api.calls[-1][1], '/api/pty/session-1/close')

    def test_existing_cli_routes_pty_locally_without_command_submission(self):
        import io
        from unittest.mock import patch
        import rchcli
        receiver = object()
        api = FakeApi()
        api.connections = lambda: [
            {'client_id': 'client-A', 'hostname': 'Mac', 'connection_state': 'online',
             'connected_at': '2026-11-01T00:00:00'}]
        commands = iter(['0', ':pty /bin/zsh', 'bg', 'quit'])
        out = io.StringIO()
        console = rchcli.RemoteConsole(api, receiver, 'tab-id', output=out,
                                       reader=lambda _: next(commands),
                                       ws_url='ws://host/ws/events')
        with patch('rchcli_pty.run_pty') as run:
            console.repl()
        run.assert_called_once_with(api, 'client-A', 'ws://host/ws/events', shell='/bin/zsh')
        self.assertEqual(api.calls, [])
        self.assertIn('[PTY closed]', out.getvalue())

    def test_full_screen_terminal_close_state_flushes_output(self):
        api = FakeApi()
        term = ScriptedTerminal([])
        ws = FakeSocket([{'type': 'output', 'status': 'closed', 'chunks': [
            {'seq': 1, 'text': 'final frame\x1b[?1049l'}]}])
        ptycli.run_pty(api, 'abc', 'ws://host/ws/events', terminal=term,
                       connect=lambda *a, **kw: ws)
        self.assertEqual(b''.join(term.writes), b'final frame\x1b[?1049l')
        self.assertEqual(term.entries, 0)
        self.assertEqual(api.calls[-1][1], '/api/pty/session-1/close')

    @unittest.skipUnless(os.name == 'posix', 'Requires real Unix PTY')
    def test_unix_terminal_raw_mode_restores_attributes(self):
        master, slave = pty.openpty()
        try:
            old = termios.tcgetattr(slave)
            terminal = ptycli.UnixTerminal(slave, slave)
            with terminal:
                raw = termios.tcgetattr(slave)
                self.assertFalse(raw[3] & termios.ICANON)
                self.assertFalse(raw[3] & termios.ISIG)
                os.write(master, b'\x03\x1b[A')
                self.assertEqual(terminal.read_ready(), b'\x03\x1b[A')
            self.assertEqual(termios.tcgetattr(slave), old)
            with self.assertRaises(ValueError):
                with terminal:
                    raise ValueError('injected')
            self.assertEqual(termios.tcgetattr(slave), old)
        finally:
            os.close(master)
            os.close(slave)

    @unittest.skipUnless(os.name == 'posix', 'Requires Unix PTY sockets')
    def test_real_ws_with_local_pty_keystrokes_output_and_restore(self):
        from websockets.sync.server import serve
        received = queue.Queue()
        server_error = []

        def handler(ws):
            try:
                ws.send(json.dumps(status('open')))
                ws.send(json.dumps({'type': 'output', 'status': 'open',
                                    'chunks': [{'seq': 1, 'text': '\x1b[2Jscreen\r\n'}]}))
                while True:
                    msg = json.loads(ws.recv(timeout=4))
                    received.put(msg)
                    if msg.get('type') == 'input':
                        ws.send(json.dumps({'type': 'output', 'status': 'open',
                                            'chunks': [{'seq': 2, 'text': 'remote$ '}]}))
                    if msg.get('type') == 'close':
                        break
            except Exception as exc:
                server_error.append(exc)

        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
            old = termios.tcgetattr(slave)
            terminal = ptycli.UnixTerminal(slave, slave)
            with serve(handler, '127.0.0.1', 0) as server:
                port = server.socket.getsockname()[1]
                server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                server_thread.start()
                api = FakeApi()
                def request(method, path, body=None):
                    if path.endswith('/pty/open'):
                        return {'pty_session_id': 'session-1', 'ws_path': '/ws/pty/session-1?token=only-for-pty'}
                    return {'ok': True}
                api.request = request
                outcome = []
                def runner():
                    try:
                        ptycli.run_pty(api, 'abc', f'ws://127.0.0.1:{port}/ws/events',
                                       terminal=terminal)
                        outcome.append('done')
                    except BaseException as exc:
                        outcome.append(exc)
                worker = threading.Thread(target=runner, daemon=True)
                worker.start()
                deadline = time.monotonic() + 3
                while worker.is_alive() and (termios.tcgetattr(slave)[3] & termios.ICANON) and time.monotonic() < deadline:
                    time.sleep(0.01)
                
                self.assertFalse(termios.tcgetattr(slave)[3] & termios.ICANON, repr(outcome))
                os.write(master, b'\x03')
                item = received.get(timeout=3)
                self.assertEqual(item['type'], 'input')
                self.assertEqual(base64.b64decode(item['data']), b'\x03')
                os.write(master, b'\x1dq')
                worker.join(timeout=4)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcome, ['done'])
                self.assertEqual(termios.tcgetattr(slave), old)
                ready, _, _ = select.select([master], [], [], 1)
                self.assertTrue(ready)
                self.assertIn(b'\x1b[2Jscreen', os.read(master, 4096))
                server.shutdown()
                server_thread.join(timeout=2)
        finally:
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    unittest.main()
