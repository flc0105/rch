"""Windows PTY creation is isolated from the receiver's Python GIL."""
import json
import threading
import time
from types import SimpleNamespace

import pytest

from client.pty.manager import PtyManager
from core.protocol.message_types import MSG_TYPE_PTY_CLOSED, MSG_TYPE_PTY_ERROR, MSG_TYPE_PTY_OPENED


FAKE_HELPER = '''
import json, sys, time
request = json.loads(sys.stdin.buffer.readline())
mode = sys.argv[1]
if mode == 'blocking':
    # CPU loop in the helper holds *its own* interpreter's GIL.
    until = time.monotonic() + 10
    while time.monotonic() < until:
        pass
elif mode == 'error':
    print(json.dumps({'event':'error','message':'fake ConPTY failure'}), flush=True)
    sys.exit(1)
else:
    print(json.dumps({'event':'stage','value':'shell spawn'}), flush=True)
    print(json.dumps({'event':'opened','pid':4412}), flush=True)
    for line in sys.stdin:
        command = json.loads(line)
        if command['op'] == 'input':
            print(json.dumps({'event':'output','text':command['text']}), flush=True)
        if command['op'] == 'close':
            break
    print(json.dumps({'event':'closed','exit_code':0}), flush=True)
'''


class Connection:
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def send(self, message):
        with self.lock:
            self.messages.append(message)

    def events(self, event):
        with self.lock:
            return [m for m in self.messages if m['type'] == event]


def until(check, seconds=2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return bool(check())


@pytest.fixture
def setup(monkeypatch, tmp_path):
    import client.pty.manager as manager_module
    monkeypatch.setattr(manager_module, 'os', SimpleNamespace(name='nt'))
    script = tmp_path / 'helper.py'
    script.write_text(FAKE_HELPER)
    conn = Connection()
    manager = PtyManager(conn)
    backend = manager.windows_backend
    monkeypatch.setattr(backend, '_worker_path', lambda: script)
    monkeypatch.setattr(backend, 'build_windows_command', lambda shell: ('cmd.exe', 'cmd.exe'))
    processes = []
    # Choose fake-worker behavior via command line argument, not extra project code.
    import subprocess, sys

    def launch(mode='normal'):
        proc = subprocess.Popen(
            [sys.executable, '-u', str(script), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0,
        )
        processes.append(proc)
        return proc

    monkeypatch.setattr(backend, '_launch', lambda: launch('normal'))
    yield manager, backend, conn, launch, monkeypatch, processes
    manager.close_all_sessions(notify=False)
    for proc in processes:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=2)


def test_open_input_output_resize_and_close(setup):
    import base64
    manager, backend, conn, _, _, _ = setup
    assert manager.open_session('success')
    assert until(lambda: bool(conn.events(MSG_TYPE_PTY_OPENED)))
    manager.write_input('success', base64.b64encode('你好\n'.encode()).decode())
    assert until(lambda: any(msg['type'] == 'pty_output' for msg in conn.messages))
    manager.resize_session('success', 90, 30)
    manager.close_session('success')
    assert until(lambda: bool(conn.events(MSG_TYPE_PTY_CLOSED)))


def test_native_style_helper_hang_does_not_block_client_heartbeat_or_timer(setup):
    manager, backend, conn, launch, monkeypatch, processes = setup
    monkeypatch.setattr(backend, '_launch', lambda: launch('blocking'))
    manager.WINDOWS_OPEN_TIMEOUT_SECONDS = .25
    start = time.monotonic()
    assert manager.open_session('blocked')
    # Simulate other inbound messages being processed on the receiver thread.
    assert time.monotonic() - start < .15
    conn.send({'type':'heartbeat_ack','id':3})
    assert conn.events('heartbeat_ack')
    assert until(lambda: bool(conn.events(MSG_TYPE_PTY_ERROR)))
    assert time.monotonic() - start < 1.5
    assert 'timed out' in conn.events(MSG_TYPE_PTY_ERROR)[0]['message']
    assert not conn.events(MSG_TYPE_PTY_OPENED)
    assert until(lambda: processes[0].poll() is not None)
    assert manager.get_session('blocked') is None


def test_close_during_native_start_kills_worker_and_prevents_late_open(setup):
    manager, backend, conn, launch, monkeypatch, processes = setup
    monkeypatch.setattr(backend, '_launch', lambda: launch('blocking'))
    assert manager.open_session('pending')
    assert until(lambda: bool(processes))
    manager.close_session('pending')
    assert until(lambda: processes[0].poll() is not None)
    assert not conn.events(MSG_TYPE_PTY_OPENED)
    assert not conn.events(MSG_TYPE_PTY_ERROR)


def test_helper_error_returns_pty_error(setup):
    manager, backend, conn, launch, monkeypatch, _ = setup
    monkeypatch.setattr(backend, '_launch', lambda: launch('error'))
    manager.open_session('failed')
    assert until(lambda: bool(conn.events(MSG_TYPE_PTY_ERROR)))
    assert 'fake ConPTY failure' in conn.events(MSG_TYPE_PTY_ERROR)[0]['message']
    assert manager.get_session('failed') is None


def test_connection_close_cancels_pending_open(setup):
    manager, backend, conn, launch, monkeypatch, processes = setup
    monkeypatch.setattr(backend, '_launch', lambda: launch('blocking'))
    manager.open_session('pending')
    assert until(lambda: bool(processes))
    manager.close_all_sessions(notify=False)
    assert until(lambda: processes[0].poll() is not None)
    assert not conn.events(MSG_TYPE_PTY_OPENED)


def test_cold_start_retries_in_new_process_and_opens(setup):
    manager, backend, conn, launch, monkeypatch, processes = setup
    backend.NATIVE_START_TIMEOUT_SECONDS = 1.3
    manager.WINDOWS_OPEN_TIMEOUT_SECONDS = 4.2
    calls = iter(('blocking', 'normal'))
    monkeypatch.setattr(backend, '_launch', lambda: launch(next(calls)))
    assert manager.open_session('retry')
    assert until(lambda: bool(conn.events(MSG_TYPE_PTY_OPENED)), 4.5), repr((conn.messages, [p.poll() for p in processes]))
    assert not conn.events(MSG_TYPE_PTY_ERROR)
    assert len(processes) == 2
    assert processes[0].poll() is not None
    manager.close_session('retry')


def test_two_stuck_processes_fail_with_stage_and_reclaim_both(setup):
    manager, backend, conn, launch, monkeypatch, processes = setup
    backend.NATIVE_START_TIMEOUT_SECONDS = 1.3
    manager.WINDOWS_OPEN_TIMEOUT_SECONDS = 4.2
    monkeypatch.setattr(backend, '_launch', lambda: launch('blocking'))
    assert manager.open_session('twice')
    assert until(lambda: bool(conn.events(MSG_TYPE_PTY_ERROR)), 4.5)
    error = conn.events(MSG_TYPE_PTY_ERROR)[0]['message']
    assert 'ConPTY startup stuck' in error
    assert 'attempt 2/2' in error
    assert len(processes) == 2
    assert until(lambda: all(proc.poll() is not None for proc in processes))
    assert not conn.events(MSG_TYPE_PTY_OPENED)


def test_old_session_cannot_finalize_replacement(setup):
    manager, backend, conn, _, _, _ = setup
    stale = SimpleNamespace(pty_session_id='reused', backend=backend)
    current = SimpleNamespace(pty_session_id='reused', backend=backend)
    manager.register_session(current)
    assert manager.finalize_session('reused', expected_session=stale) is None
    assert manager.get_session('reused') is current
    manager.finalize_session('reused', expected_session=current)
    assert manager.get_session('reused') is None
