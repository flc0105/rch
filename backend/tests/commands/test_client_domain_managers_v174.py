"""Control domains execute without constructing a platform command instance."""
import os
import threading
import time
from types import SimpleNamespace

from client.config import runtime_config
from client.runtime.client_runtime import ClientRuntime
from client.runtime.execution.runtime import ExecutionRuntime


def make_runtime():
    sent = []
    socket = SimpleNamespace(client_id='test', client_session_token='', info={}, send_result=lambda *args: sent.append(args))
    runtime = ClientRuntime(socket, features={'pty': False, 'screen_view': False, 'clipboard': False})
    socket.runtime = runtime
    return runtime, sent


def test_three_domains_do_not_instantiate_commands(tmp_path, monkeypatch):
    runtime, _ = make_runtime()
    def forbidden(*args, **kwargs):
        raise AssertionError('Control must not instantiate Commands')
    monkeypatch.setattr(runtime.command_executor, 'get_commands', forbidden)
    monkeypatch.setattr(runtime_config, 'SCRIPT_DEFAULT_EXECUTION_MODE', 'inproc')
    dispatch = runtime.control_dispatcher.execute
    assert dispatch(1, 'job', 'ps', {})[0] == 1
    src = tmp_path / 'a.txt'
    src.write_text('data')
    dest = tmp_path / 'dest'
    dest.mkdir()
    (dest / 'a.txt').write_text('old')
    status, report = dispatch(2, 'remote_files', 'paste_paths', {
        'paths': [str(src)], 'destination_dir': str(dest), 'operation': 'move', 'conflict_policies': ['skip'],
    })
    assert status == 1 and report['skipped'] == 1 and src.read_text() == 'data'
    assert (dest / 'a.txt').read_text() == 'old'
    status, report = dispatch(3, 'remote_files', 'delete_paths', {'paths': [str(src)]})
    assert status == 1 and report['succeeded'] == 1 and not src.exists()
    assert dispatch(4, 'script', 'run', {'script_name':'demo','source':'print(kwargs["x"])','params':{'x':42},'execution_mode':'inproc','output_mode':'collect'}) == (1, '42\n')
    assert dispatch(5, 'remote_files', 'browse_directory', {'path': str(tmp_path)})[0] == 1
    assert all(runtime.execution.context_store.get_existing(i) is None for i in range(1,6))


def test_sdk_explicit_command_access_is_preserved(monkeypatch):
    runtime, _ = make_runtime()
    monkeypatch.setattr(runtime_config, 'SCRIPT_DEFAULT_EXECUTION_MODE', 'inproc')
    status, output = runtime.control_dispatcher.execute(6, 'script', 'run', {
        'script_name':'demo', 'source': 'print(command.run_client("cd", "").output)', 'params': {}, 'execution_mode':'inproc','output_mode':'collect',
    })
    assert status == 1, output
    assert output.strip() == os.getcwd()
    assert runtime.execution.context_store.get_existing(6) is None
    commands = runtime.command_executor.get_commands()
    for name in ('browse_dir', 'delete_paths', 'paste_paths', 'save_file_content', 'execute_script_stream', 'start_job'):
        assert not hasattr(commands, name), name


def test_shared_execution_cancels_script_subprocess(monkeypatch):
    runtime, _ = make_runtime()
    monkeypatch.setattr(runtime_config, 'SCRIPT_DEFAULT_EXECUTION_MODE', 'subprocess_pipe')
    results = []
    worker = threading.Thread(target=lambda: results.append(runtime.control_dispatcher.execute(7, 'script','run', {
        'script_name':'demo', 'source':'import time\ntime.sleep(30)', 'params': {}, 'execution_mode':'subprocess_pipe','output_mode':'collect',
    })), daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        context = runtime.execution.context_store.get_existing(7)
        if context is not None and context.is_cancel_supported() and context._cancel_handlers:
            break
        time.sleep(.01)
    else:
        raise AssertionError('Script cancellation handler not installed')
    assert runtime.execution.cancel(7)['accepted']
    worker.join(5)
    assert not worker.is_alive()
    assert results and results[0][0] == 0 and results[0][1]['event_type'] == 'cancelled'
    assert runtime.execution.context_store.get_existing(7) is None
