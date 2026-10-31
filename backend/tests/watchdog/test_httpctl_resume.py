"""Remote resume control delivery, precise offline targeting, and Worker ACKs."""
import time
from types import SimpleNamespace

import pytest

from server.application.command import control_builtin_support as builtin_module
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.connection.control_command_store import ControlCommandStore
from client.watchdog.remote_control_watchdog import RemoteControlWatchdogMonitor


def test_offline_client_resume_is_queued_and_acknowledged():
    store = ControlCommandStore()
    request = store.set_pending_command('paused-original', 'resume')
    assert store.pop_pending_command('another-client') is None
    assert store.pop_pending_command('paused-original') == request
    outcome = store.acknowledge_control('paused-original', request['command_id'], 'delivered')
    assert outcome['status'] == 'delivered'
    assert outcome['command'] == 'resume'
    assert store._expiry_timers == {}


def test_resume_failure_ack_and_wrong_client_rejected():
    store = ControlCommandStore()
    request = store.set_pending_command('paused-original', 'resume')
    with pytest.raises(ValueError, match='not been received'):
        store.acknowledge_control('paused-original', request['command_id'], 'delivered')
    store.pop_pending_command('paused-original')
    with pytest.raises(ValueError, match='Unknown'):
        store.acknowledge_control('another-client', request['command_id'], 'delivered')
    outcome = store.acknowledge_control('paused-original', request['command_id'], 'failed', 'IPC unavailable')
    assert outcome['status'] == 'failed'
    assert outcome['detail'] == 'IPC unavailable'


def test_unclaimed_resume_times_out_without_evicting_other_requests():
    store = ControlCommandStore()
    store.CONTROL_TIMEOUT_SECONDS = {**store.CONTROL_TIMEOUT_SECONDS, 'resume': 0.03}
    failed = []
    store.set_timeout_callback(failed.append)
    store.set_pending_command('paused-original', 'resume')
    other = store.set_pending_command('other-client', 'clone')
    time.sleep(.08)
    assert len(failed) == 1 and failed[0]['command'] == 'resume'
    assert failed[0]['status'] == 'timeout'
    assert store.pop_pending_command('paused-original') is None
    assert store.pop_pending_command('other-client') == other
    store.acknowledge_control('other-client', other['command_id'], 'delivered')


def test_server_builtin_resume_explicit_offline_target(monkeypatch):
    store = ControlCommandStore()
    monkeypatch.setattr(builtin_module, 'get_control_command_store', lambda: store)
    support = builtin_module.ControlBuiltinSupport(SimpleNamespace(session_info=None))
    ok, text = next(support.httpctl('resume --client-id paused-original'))
    assert ok == 1
    assert 'paused-original' in text
    assert store.pop_pending_command('paused-original')['command'] == 'resume'
    assert next(support.httpctl('resume'))[0] == 0
    assert next(support.httpctl('kill --client-id other-client'))[0] == 0
    assert store.pop_pending_command('other-client') is None
    assert next(support.httpctl('resume --client-id'))[0] == 0
    assert next(support.httpctl('resume --unknown bad'))[0] == 0
    assert SERVER_COMMAND_REGISTRY.parse('httpctl', 'resume --client-id paused-original')[1:] == ('resume', '--client-id paused-original')


def test_server_builtin_legacy_commands_unchanged(monkeypatch):
    store = ControlCommandStore()
    monkeypatch.setattr(builtin_module, 'get_control_command_store', lambda: store)
    support = builtin_module.ControlBuiltinSupport(SimpleNamespace(session_info=SimpleNamespace(client_id='online-1')))
    for name in ('kill', 'relaunch', 'clone'):
        assert next(support.httpctl(name))[0] == 1
        assert store.pop_pending_command('online-1')['command'] == name
    assert next(support.httpctl('resume'))[0] == 1
    assert store.pop_pending_command('online-1')['command'] == 'resume'


def _worker(tmp_path):
    return RemoteControlWatchdogMonitor(
        client_id='paused-original', base_url='http://127.0.0.1:8085',
        poll_interval=15, remote_control_watchdog_log_file_path=str(tmp_path / 'remote.log'),
        action_executor=SimpleNamespace(),
    )


def test_remote_worker_acknowledges_successful_resume(monkeypatch, tmp_path):
    worker = _worker(tmp_path)
    called = []
    monkeypatch.setattr(worker, '_fetch_command', lambda: {'command': 'resume', 'command_id': 'id1'})
    monkeypatch.setattr('client.watchdog.remote_control_watchdog.send_local_command', lambda action: called.append(action))
    monkeypatch.setattr(worker, '_report_control_result', lambda *args: called.append(args))
    worker.run_iteration(time.monotonic())
    assert called == ['connection.resume', ('id1', 'delivered')]


def test_remote_worker_reports_failed_ipc(monkeypatch, tmp_path):
    worker = _worker(tmp_path)
    called = []
    monkeypatch.setattr(worker, '_fetch_command', lambda: {'command': 'resume', 'command_id': 'id2'})
    def missing_ipc(_):
        raise RuntimeError('Client local IPC is unavailable')
    monkeypatch.setattr('client.watchdog.remote_control_watchdog.send_local_command', missing_ipc)
    monkeypatch.setattr(worker, '_report_control_result', lambda *args: called.append(args))
    worker.run_iteration(time.monotonic())
    assert called == [('id2', 'failed', 'Client local IPC is unavailable')]


def test_outer_server_shell_can_wake_offline_instance_without_selected_session(monkeypatch):
    from server.runtime.command_shell import ServerCommandShell
    store = ControlCommandStore()
    monkeypatch.setattr(builtin_module, 'get_control_command_store', lambda: store)
    shell = ServerCommandShell.__new__(ServerCommandShell)
    shell._handle_console_command('httpctl resume --client-id paused-original')
    assert store.pop_pending_command('paused-original')['command'] == 'resume'
