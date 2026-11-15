"""Exercise real framed socket dispatch, foreground execution and independent queries."""
import queue
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from client.connection.server_connection import ServerConnection
from core.protocol.control import ControlDomain, RemoteFilesAction, ExecutionPolicy
from client.clipboard.manager import ClipboardManager
from server.connection.client_session import ClientSession
from server.connection.transport.client_transport import ClientTransport
from server.application.clipboard.clipboard_session_service import ClipboardSessionService
from server.application.execution.remote_execution_service import RemoteExecutionService
from server.application.artifact.remote_file_service import WebRemoteFileService


class MemoryClipboard:
    def __init__(self):
        self.text = 'initial'
    def get_capabilities(self):
        return {'text': True}
    def get_snapshot(self):
        return {'kind': 'text', 'text': self.text}
    def set_text(self, text):
        self.text = text


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setattr(ClipboardManager, '_build_adapter', lambda self: MemoryClipboard())
    monkeypatch.setattr('client.clipboard.manager.get_temp_category_dir', lambda *a, **kw: str(tmp_path / 'staging'))
    client = ServerConnection(features={'pty': False, 'screen_view': False, 'clipboard': True})
    a, b = socket.socketpair()
    client.socket.close()
    client.socket = a
    client.mark_connected()
    server = ClientSession(ClientTransport(b), {'id': 'test'})
    stop = threading.Event()
    errors = []
    def recv_loop(conn):
        try:
            while not stop.is_set():
                conn.recv_message()
        except OSError:
            pass
        except Exception as exc:
            errors.append(exc)
    def foreground():
        try:
            while not stop.is_set():
                try:
                    result = client.recv_command(timeout=.1)
                except queue.Empty:
                    continue
                if result:
                    client.send_result(*result)
        except OSError:
            pass
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=recv_loop, args=(conn,), daemon=True) for conn in (client, server)]
    threads.append(threading.Thread(target=foreground, daemon=True))
    for thread in threads:
        thread.start()
    yield client, server
    stop.set()
    client.runtime.control_dispatcher.disconnect()
    for conn in (a,b):
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        conn.close()
    server.runtime.pending_results.close()
    for thread in threads:
        thread.join(3)
    assert not errors, errors


@pytest.mark.parametrize("mode", ["inproc", "subprocess_pipe"])
def test_script_clipboard_and_files_real_wire(wire, tmp_path, mode):
    client, server = wire
    target = SimpleNamespace(get_target_connection_by_client_id=lambda _: server)
    clipboard = ClipboardSessionService(target)
    files = WebRemoteFileService(RemoteExecutionService(target), None)
    (tmp_path / 'needle.txt').write_text('test')
    server.acquire_foreground_task('script', 'probe', cancel_policy='process' if mode == 'subprocess_pipe' else 'none')
    rows = server.send_command('', type='control', domain='script', action='run', payload={
        'script_name': 'test/probe', 'source': 'import time\nprint("ready", flush=True)\ntime.sleep(%d)\nprint("done")' % (20 if mode == 'subprocess_pipe' else 3),
        'params': {}, 'execution_mode': mode, 'output_mode': 'stream',
    })
    assert 'ready' in str(next(rows)[1])
    command_id = server.get_foreground_task()['command_id']
    assert command_id == 1
    assert clipboard.get_clipboard('test')['text'] == 'initial'
    assert clipboard.set_clipboard('test', {'kind':'text','text':'updated'}, action='set_text')['message'] == 'Target clipboard updated'
    assert clipboard.get_clipboard('test')['text'] == 'updated'
    listing = files.browse_directory('test', str(tmp_path))
    assert 'needle.txt' in str(listing['entries'])
    assert server.get_foreground_task()['command_id'] == command_id
    assert client.runtime.execution.context_store.get_existing(command_id) is not None
    if mode == 'subprocess_pipe':
        server.send_cancel(command_id)
        result = list(rows)
        assert result[-1][0] == 0 and 'cancelled' in str(result[-1][1]).lower()
    else:
        result = list(rows)
        assert result[-1][0] == 1 and 'done' in str(result)
    server.release_foreground_task(command='probe')
    assert not server.runtime.pending_results._items
    assert clipboard.get_clipboard('test')['text'] == 'updated'


def test_out_of_order_cancel_timeout_disconnect(wire, tmp_path):
    client, server = wire
    entered = threading.Event()
    def slow(scope, action, payload):
        entered.set()
        while True:
            scope._checkpoint()
            time.sleep(.01)
    dispatcher = client.runtime.control_dispatcher
    dispatcher.register(ControlDomain.REMOTE_FILES, RemoteFilesAction.PEEK_ARCHIVE, slow, policy=ExecutionPolicy.INDEPENDENT, cancel_policy='cooperative')
    def request(timeout=5):
        return server.send_command('', type='control',domain='remote_files',action='peek_archive',payload={},extra={'timeout':timeout})
    first = request()
    assert entered.wait(2)
    second = server.send_command('',type='control',domain='remote_files',action='browse_directory',payload={'path':str(tmp_path)})
    assert list(second)[-1][0] == 1
    server.send_cancel(1)
    assert list(first)[-1][1]['event_type'] == 'cancelled'
    with pytest.raises(TimeoutError):
        list(request(.1))
    # An abandoned request cannot deliver into another pending stream.
    assert not server.runtime.pending_results.deliver(1, {'type':'result','id':1,'event_type':'completed','status':'success','message':'late'})
    entered.clear()
    waiting = request()
    assert entered.wait(2)
    server.transport.shutdown()
    server.close()
    assert list(waiting) == [(0,None)]
    assert not server.runtime.pending_results._items
    client.runtime.handle_connection_lost()
    deadline = time.monotonic()+3
    while dispatcher._active and time.monotonic()<deadline:
        time.sleep(.01)
    assert not dispatcher._active
    assert not client.runtime.execution.context_store.get_existing(1)


def test_replaced_connection_pending_results_are_session_scoped():
    from server.connection.connection_manager import ConnectionManager
    from server.runtime.session_acceptor import SessionAcceptor
    from server.connection.runtime.session_runtime import ClientSessionRuntime
    manager = ConnectionManager()
    def session():
        return SimpleNamespace(session_info=SimpleNamespace(client_id='same'), context=SimpleNamespace(),
                               runtime=ClientSessionRuntime(), address='test')
    old, new = session(), session()
    first = old.runtime.pending_results.register(1)
    second = new.runtime.pending_results.register(1)
    manager.add(old)
    manager.add(new)
    closed, replaced = [], []
    api = SimpleNamespace(handle_connection_closed=closed.append, handle_replaced_connection_closed=replaced.append)
    acceptor = SessionAcceptor(SimpleNamespace(connections=manager, web_service=SimpleNamespace(connection_api=api)))
    acceptor._handle_connection_closed(old)
    assert closed == [] and replaced == [old]
    assert first.get(timeout=.1)['status'] == 'interrupted'
    assert manager.get_by_client_id('same') is new
    assert new.runtime.pending_results.deliver(1, {'type':'result','id':1,'event_type':'completed','status':'success','message':'new'})
    assert second.get(timeout=.1)['message'] == 'new'


def test_new_independent_actions_during_foreground_script(wire, tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    from core.protocol.control import ConfigurationAction, WatchdogAction, JobAction, ProcessAction
    from server.application.jobs.background_job_service import BackgroundJobService
    from server.application.web.command_execution_api import WebCommandExecutionApi
    from server.application.web.process_control_api import WebProcessControlApi

    client, server = wire
    target = SimpleNamespace(get_target_connection_by_client_id=lambda _: server)
    execution = RemoteExecutionService(target)
    files = WebRemoteFileService(execution, None)
    jobs = BackgroundJobService(None, None, execution, None)
    config = WebCommandExecutionApi(None, remote_execution_service=execution)
    process = WebProcessControlApi(target, execution)
    server.acquire_foreground_task('script', 'probe', cancel_policy='process')
    rows = server.send_command('', type='control', domain='script', action='run', payload={
        'script_name': 'test/probe', 'source': 'import time\nprint("ready", flush=True)\ntime.sleep(30)',
        'params': {}, 'execution_mode': 'subprocess_pipe', 'output_mode': 'stream',
    })
    assert 'ready' in str(next(rows)[1])
    command_id = server.get_foreground_task()['command_id']
    try:
        assert config.get_runtime_config('test')['data']['items']
        assert 'client' in config.get_watchdog_status('test')
        assert 'No background jobs' in jobs._execute_job_action('test', JobAction.PS, {})
        assert 'not_running' in jobs._execute_job_action('test', JobAction.STATUS, {'job_key': 'not-running'})
        with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) as child:
            try:
                assert process.kill_process('test', child.pid)['message']
                child.wait(timeout=5)
            finally:
                if child.poll() is None:
                    child.kill()
        original = tmp_path / 'source.txt'
        original.write_text('original')
        dest = tmp_path / 'destination'
        files.create_directory('test', str(dest))
        assert dest.is_dir()
        files.save_file_content('test', str(original), 'changed')
        assert original.read_text() == 'changed'
        files.rename_path('test', str(original), 'renamed.txt')
        renamed = tmp_path / 'renamed.txt'
        assert renamed.exists() and not original.exists()
        files.paste_paths('test', [str(renamed)], str(dest))
        assert (dest / 'renamed.txt').read_text() == 'changed'
        archived = files.create_zip_from_paths('test', [str(renamed)], str(tmp_path), 'archive.zip')
        archive_path = archived['archive_path']
        extraction = tmp_path / 'extraction'
        files.create_directory('test', str(extraction))
        assert isinstance(files.extract_zip('test', archive_path, str(extraction), inspect=True), dict)
        result = files.extract_zip('test', archive_path, str(extraction))
        assert (Path(result['extracted_to']) / 'renamed.txt').read_text() == 'changed'
        files.delete_paths('test', [str(renamed)])
        assert not renamed.exists()
        assert server.get_foreground_task()['command_id'] == command_id
        assert client.runtime.execution.context_store.get_existing(command_id) is not None
    finally:
        server.send_cancel(command_id)
        assert list(rows)[-1][0] == 0
        server.release_foreground_task(command='probe')
    assert not server.runtime.pending_results._items


@pytest.mark.parametrize('mode,output', [('inproc','collect'),('inproc','stream'),('subprocess_pipe','collect'),('subprocess_pipe','stream')])
def test_script_warning_activity_uses_terminal_result(wire, tmp_path, mode, output):
    import sys
    from types import ModuleType
    from unittest.mock import patch
    config = ModuleType('server.config.config')
    for name, value in {'COMMAND_HISTORY_RECENT_LIMIT':100, 'COMMAND_HISTORY_PAGE_SIZE':50,
                        'COMMAND_HISTORY_MAX_PAGE_SIZE':200, 'COMMAND_HISTORY_MAX_OUTPUT_RECORD_CHARS':65536,
                        'COMMAND_HISTORY_MAX_OUTPUT_RECORDS':256}.items():
        setattr(config, name, value)
    with patch.dict(sys.modules, {'server.config.config':config}):
        from server.application.history.history_store import CommandHistoryStore
        from server.application.history.activity_coordinator import ActivityCoordinator
        from server.application.history.command_dispatch_adapter import CommandDispatchAdapter
    from server.persistence.rch_database import RchDatabase
    client, server = wire
    db = RchDatabase(str(tmp_path / 'activity.db'))
    store = CommandHistoryStore(db)
    coordinator = ActivityCoordinator(store)
    server.context.activity_coordinator = coordinator
    server.context.command_dispatch_adapter = CommandDispatchAdapter(coordinator, lambda _:server)
    source = 'from client.runtime.sdk import context\ncontext.progress("[WARNING] optional file missing", level="warning")\nprint("Not approved")'
    rows = list(server.send_command('', type='control', domain='script', action='run', payload={
        'script_name':'test/warning', 'source':source, 'params':{}, 'execution_mode':mode, 'output_mode':output}))
    assert rows[-1][0] == 1 and rows[-1].eof
    history = store.view_service.get_execution_history_page('unknown_machine')['items']
    assert len(history) == 1 and history[0]['status'] == 'success'
    assert 'Not approved' in str(history[0]['result'])
    db.close_thread_connection()
