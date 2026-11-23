"""Active Update handoff: readiness from real connection events and one-shot workers."""
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.commands.shell.standalone import update as update_command
from client.connection.bind_listener import BindListener
from client.connection.message_dispatcher import ClientInboundMessageDispatcher
from client.update import preparation, signals
from client.update.handoff import run_handoff


def test_build_request_includes_real_bind_settings(monkeypatch):
    monkeypatch.setattr(preparation, 'RUNTIME_CONFIG', {
        'connection_mode': 'bind', 'bind_host': '0.0.0.0', 'bind_port': 9443,
    })
    payload = preparation.build_request()
    assert payload['connection_mode'] == 'bind'
    assert payload['bind_host'] == '0.0.0.0'
    assert payload['bind_port'] == 9443
    assert 'server_tls_fingerprint' not in payload
    monkeypatch.setattr(preparation, 'RUNTIME_CONFIG', {
        'connection_mode': 'reverse', 'server_transport': 'tls_tcp',
        'server_tls_fingerprint': 'f' * 64,
    })
    reverse = preparation.build_request()
    assert reverse['connection_mode'] == 'reverse'
    assert reverse['server_transport'] == 'tls_tcp'
    assert reverse['server_tls_fingerprint'] == 'f' * 64


def test_options_and_managed_restrictions(monkeypatch):
    assert update_command._parse_update_options('') == {'keep_old': False}
    assert update_command._parse_update_options('--keep-old') == {'keep_old': True}
    with pytest.raises(ValueError):
        update_command._parse_update_options('--keep-old --keep-old')
    monkeypatch.setattr(update_command, 'get_local_identity', lambda: SimpleNamespace(os_alias='linux'))
    monkeypatch.setattr(update_command, 'detect_launch_context', lambda _: {'source': 'systemd'})
    with pytest.raises(RuntimeError, match='not supported'):
        update_command._get_update_owner()


def _candidate_signal(monkeypatch, listener, mode):
    for key, value in signals.candidate_environment(listener.port, listener.secret, 'try-1').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(signals, '_reported', False)
    monkeypatch.setattr(signals, 'CLIENT_SOURCE_REVISION', 'test-revision')
    signals.set_recovery_manager(None)
    signals.set_client_watchdog_manager(None)


def test_bind_ready_only_after_listen(monkeypatch):
    process = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    with signals.SignalListener() as signal:
        _candidate_signal(monkeypatch, signal, 'bind')
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        listener = BindListener({'connection_mode': 'bind', 'bind_host': '127.0.0.1', 'bind_port': port})
        try:
            listener.start()
            assert listener._socket is not None
            packet = signal.accept(attempt_id='try-1', process=process,
                                   revision='test-revision', mode='bind', stable_seconds=.03)
            assert packet['mode'] == 'bind' and packet['pid'] == os.getpid()
        finally:
            listener.close()


def test_reverse_ready_requires_server_session_token(monkeypatch):
    process = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    with signals.SignalListener() as signal:
        _candidate_signal(monkeypatch, signal, 'reverse')
        from client.http import session_auth
        monkeypatch.setattr(session_auth, 'set_token', lambda *_: None)
        connection = SimpleNamespace(client_id='client-a', client_session_token='')
        dispatcher = ClientInboundMessageDispatcher(connection)
        dispatcher.dispatch({'type': 'client_session_token', 'token': ''})
        assert not signals._reported
        dispatcher.dispatch({'type': 'client_session_token', 'token': 'session-issued'})
        packet = signal.accept(attempt_id='try-1', process=process,
                               revision='test-revision', mode='reverse', stable_seconds=.03)
        assert packet['client_id'] == 'client-a'


def test_signal_rejects_wrong_mode():
    process = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    with signals.SignalListener() as signal:
        def send():
            with socket.create_connection(('127.0.0.1', signal.port), timeout=2) as conn:
                conn.settimeout(5)
                conn.sendall((json.dumps({'secret': signal.secret, 'attempt_id': 'a',
                                          'pid': os.getpid(), 'client_revision': 'r',
                                          'mode': 'reverse', 'client_id': 'c'}) + '\n').encode())
                assert not json.loads(conn.recv(1024))['accepted']
        thread = threading.Thread(target=send)
        thread.start()
        with pytest.raises(ValueError, match='mode mismatch'):
            signal.accept(attempt_id='a', process=process, revision='r', mode='bind')
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_launchd_stable_entry_replaces_process(tmp_path):
    from client.update import launchd_entry
    script = tmp_path / 'client.py'
    script.write_text('import os, sys\nprint("ready", sys.argv[1], os.environ.get("RCH_UPDATE_ATTEMPT"), flush=True)\n')
    job = tmp_path / 'job.json'
    job.write_text(json.dumps({'script': str(script), 'args': ['example'],
                               'update_environment': {'RCH_UPDATE_ATTEMPT': 'attempt'}}))
    result = subprocess.run([sys.executable, launchd_entry.__file__, str(job)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert 'ready example attempt' in result.stdout


def test_one_shot_bind_handoff_with_real_process(tmp_path):
    from client.update.handoff import run_handoff
    pid_file = tmp_path / 'candidate.pid'
    candidate = tmp_path / 'candidate.py'
    candidate.write_text('''import json, os, socket, time
with open(os.environ['TEST_CANDIDATE_PID'], 'w') as handle: handle.write(str(os.getpid()))
with socket.create_connection(('127.0.0.1', int(os.environ['RCH_UPDATE_SIGNAL_PORT'])), timeout=5) as sock:
    sock.settimeout(10)
    sock.sendall((json.dumps({'secret': os.environ['RCH_UPDATE_SIGNAL_SECRET'],
      'attempt_id': os.environ['RCH_UPDATE_ATTEMPT'], 'pid': os.getpid(),
      'mode': 'bind', 'client_revision': 'test-revision', 'client_id': ''})+'\\n').encode())
    reply = sock.recv(1024)
    if b'true' not in reply: raise RuntimeError(reply)
time.sleep(5)
''')
    plan = {'attempt': 'test-actual', 'mode': 'bind', 'old_pid': 999999999,
            'candidate_script': str(candidate), 'revision': 'test-revision',
            'previous_argv': [sys.executable, str(candidate)], 'previous_cwd': str(tmp_path),
            'launchd': None}
    monkey_env = os.environ.copy()
    os.environ['TEST_CANDIDATE_PID'] = str(pid_file)
    try:
        run_handoff(plan)
        pid = int(pid_file.read_text())
        assert pid > 0
    finally:
        os.environ.clear()
        os.environ.update(monkey_env)
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 15)
            except ProcessLookupError:
                pass


def test_launchd_handoff_installs_fixed_entry_once_and_restores_plist(tmp_path, monkeypatch):
    from client.update import launchd_handoff
    import plistlib
    plist = tmp_path / 'com.example.rch.plist'
    previous = {'Label': 'com.example.rch', 'ProgramArguments': ['python', '/old/rchclient.py'],
                'WorkingDirectory': '/old', 'KeepAlive': True, 'RunAtLoad': True,
                'EnvironmentVariables': {'TEST_RCH': 'kept'}}
    plist.write_bytes(plistlib.dumps(previous))
    root = tmp_path / 'bundle'
    (root / 'releases').mkdir(parents=True)

    class FakeManager:
        def __init__(self, **_kwargs):
            self.target = SimpleNamespace(
                service_target='system/com.example.rch', plist_path=str(plist))
            self.loaded = False

        def _require_control_privilege(self):
            pass

        def _require_install_privilege(self):
            pass

        def stop(self):
            self.loaded = False

        def start(self):
            self.loaded = True
            return {'pid': os.getpid()}

        def status(self):
            return {'pid': os.getpid() if self.loaded else None, 'running': self.loaded}

        def _write_plist(self, data):
            plist.write_bytes(plistlib.dumps(data))

    monkeypatch.setattr(launchd_handoff, 'LaunchdServiceManager', FakeManager)
    monkeypatch.setattr(launchd_handoff, 'get_client_bundle_release_dir',
                        lambda: str(root / 'releases'))
    monkeypatch.setattr(launchd_handoff, '_resolve_python_command_for_source_bundle',
                        lambda: ['python'])
    context = dict(source='launchdaemon', service_label='com.example.rch',
                   service_target='system/com.example.rch', service_plist=str(plist))
    updater = launchd_handoff.LaunchdUpdateHandoff(context, '/new/rchclient.py',
                                                   {'RCH_UPDATE_SIGNAL_SECRET': 'short-lived'})
    assert updater.first_install
    assert updater.activate().poll() is None
    changed = plistlib.loads(plist.read_bytes())
    assert changed['EnvironmentVariables'] == previous['EnvironmentVariables']
    assert changed['ProgramArguments'][1] == str(root / 'launchd_launcher.py')
    state = json.loads(Path(updater.state_path).read_text())
    assert state['script'] == '/new/rchclient.py'
    assert state['update_environment']['RCH_UPDATE_SIGNAL_SECRET'] == 'short-lived'
    updater.finalize()
    assert json.loads(Path(updater.state_path).read_text())['update_environment'] == {}
    migrated_plist = plist.read_bytes()
    stable_state = Path(updater.state_path).read_bytes()
    # A later Update changes only the job-specific pointer, never its plist.
    successor = launchd_handoff.LaunchdUpdateHandoff(
        context, '/newer/rchclient.py', {'RCH_UPDATE_SIGNAL_SECRET': 'transient'},
    )
    assert not successor.first_install
    assert successor.activate().poll() is None
    assert plist.read_bytes() == migrated_plist
    successor.finalize()
    assert json.loads(Path(updater.state_path).read_text())['script'] == '/newer/rchclient.py'
    successor.rollback()
    assert Path(updater.state_path).read_bytes() == stable_state
    updater.rollback()
    assert plistlib.loads(plist.read_bytes()) == previous
    assert not Path(updater.state_path).exists()


def test_candidate_failure_restores_previous_bind_without_server_redial(tmp_path):
    from client.update import handoff
    candidate = tmp_path / 'candidate.py'
    candidate.write_text('raise RuntimeError("failed to listen")\n')
    original_log = tmp_path / 'previous.pid'
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    previous = tmp_path / 'previous.py'
    previous.write_text(f'''import json, os, socket, time
from pathlib import Path
s = socket.socket()
s.bind(('127.0.0.1', {port}))
s.listen(1)
Path({str(original_log)!r}).write_text(str(os.getpid()))
with socket.create_connection(('127.0.0.1', int(os.environ['RCH_UPDATE_SIGNAL_PORT'])), timeout=5) as signal:
    signal.settimeout(10)
    signal.sendall((json.dumps({{'secret': os.environ['RCH_UPDATE_SIGNAL_SECRET'],
     'attempt_id': os.environ['RCH_UPDATE_ATTEMPT'], 'pid': os.getpid(),
     'mode': 'bind', 'client_revision': 'old-revision', 'client_id': ''}})+'\\n').encode())
    assert json.loads(signal.recv(1024))['accepted']
time.sleep(15)
''')
    log = tmp_path / 'handoff.log'
    plan = {'attempt': 'failure', 'mode': 'bind', 'old_pid': 999999999,
            'candidate_script': str(candidate), 'revision': 'rev',
            'previous_argv': [sys.executable, str(previous)], 'previous_cwd': str(tmp_path),
            'previous_revision': 'old-revision', 'launchd': None, 'log_path': str(log)}
    try:
        with pytest.raises(RuntimeError, match='before bind readiness'):
            handoff.run_handoff(plan)
        assert original_log.exists()
        recovered_pid = int(original_log.read_text())
        assert recovered_pid > 0
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            pass
        assert 'failed to listen' in log.read_text()
    finally:
        if original_log.exists():
            try:
                os.kill(int(original_log.read_text()), 15)
            except ProcessLookupError:
                pass


def test_bind_shutdown_waits_until_command_completes(monkeypatch):
    from client.commands.shell.standalone import update as command
    trace = []

    class FakeSocket:
        process_recovery_watchdog_manager = SimpleNamespace(stop=lambda: trace.append('recovery stopped'))
        watchdog_manager = SimpleNamespace(stop=lambda: trace.append('watchdog stopped'))
        def report_session_end(self, reason, *, command):
            trace.append(('server ack', reason, command))
            return True
        def close(self):
            trace.append('socket closed')

    class FakeThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            try:
                self.target()
            except SystemExit:
                pass

    from client.runtime.execution.context import ExecutionContext
    context = ExecutionContext(10)
    monkeypatch.setattr(command.threading, 'Thread', FakeThread)
    monkeypatch.setattr(command.os, '_exit', lambda status: (_ for _ in ()).throw(SystemExit(status)))
    command._schedule_exit_after_update(FakeSocket(), context)
    assert trace == []
    context.finish()
    assert trace == ['recovery stopped', 'watchdog stopped',
                     ('server ack', 'client_update', 'update'), 'socket closed']


def test_launchd_denied_plist_migration_does_not_stop_live_job(tmp_path, monkeypatch):
    """A non-privileged owner must not boot out a live global job first."""
    from client.update import launchd_handoff
    import plistlib

    plist = tmp_path / 'service.plist'
    plist.write_bytes(plistlib.dumps({
        'Label': 'com.example.test', 'ProgramArguments': ['python', '/old/client.py'],
    }))
    stops = []

    class FakeManager:
        def __init__(self, **_kwargs):
            self.target = SimpleNamespace(
                service_target='system/com.example.test', plist_path=str(plist),
            )

        def _require_control_privilege(self):
            pass

        def _require_install_privilege(self):
            raise PermissionError('requires root')

        def stop(self):
            stops.append(True)

    monkeypatch.setattr(launchd_handoff, 'LaunchdServiceManager', FakeManager)
    monkeypatch.setattr(launchd_handoff, 'get_client_bundle_release_dir',
                        lambda: str(tmp_path / 'bundle' / 'releases'))
    monkeypatch.setattr(launchd_handoff, '_resolve_python_command_for_source_bundle',
                        lambda: ['python'])
    owner = dict(source='launchdaemon', service_label='com.example.test',
                 service_target='system/com.example.test', service_plist=str(plist))
    transfer = launchd_handoff.LaunchdUpdateHandoff(owner, '/new/client.py', {})
    with pytest.raises(PermissionError, match='requires root'):
        transfer.activate()
    assert not stops
    assert plistlib.loads(plist.read_bytes())['ProgramArguments'] == ['python', '/old/client.py']


def test_bind_update_candidate_does_not_retry_failed_port_acquisition(monkeypatch):
    from client.app.client import Client
    from client.update import signals
    monkeypatch.setattr(signals, 'is_update_candidate', lambda: True)
    client = Client.__new__(Client)
    client.connection_lifecycle = SimpleNamespace(is_bind_mode=True, _bind_listener=None)
    client.connect = lambda: (_ for _ in ()).throw(OSError(98, 'Address already in use'))
    client._recover_from_connection_error = lambda error: pytest.fail('candidate must not retry bind failure')
    with pytest.raises(OSError, match='Address already in use'):
        client.connect_initial()


def test_failed_bind_recovery_does_not_claim_listening_when_port_taken(tmp_path, capsys):
    from client.update.handoff import run_handoff
    candidate = tmp_path / 'candidate.py'
    candidate.write_text('raise RuntimeError("candidate cannot listen")\n')
    previous = tmp_path / 'previous.py'
    previous.write_text('raise OSError("port already in use by another Bind process")\n')
    log = tmp_path / 'handoff.log'
    plan = {'attempt': 'occupied', 'mode': 'bind', 'old_pid': 999999999,
            'candidate_script': str(candidate), 'revision': 'rev',
            'previous_argv': [sys.executable, str(previous)], 'previous_cwd': str(tmp_path),
            'previous_revision': 'previous-rev', 'launchd': None, 'log_path': str(log)}
    with pytest.raises(RuntimeError, match='before bind readiness'):
        run_handoff(plan)
    stdout = capsys.readouterr().out
    assert 'Previous Client failed to restore listening socket' in stdout
    assert 'Previous Client listening again' not in stdout
    assert 'candidate cannot listen' in log.read_text()
    assert 'port already in use by another Bind process' in log.read_text()


def test_detached_handoff_includes_log_path_in_child_plan(tmp_path, monkeypatch):
    import subprocess as popen_module
    from client.update import handoff
    from client.runtime import client_util
    import client.watchdog.watchdog_environment as watchdog_environment
    from client.watchdog.watchdog_environment import without_process_recovery_watchdog_environment
    calls = []
    monkeypatch.setattr(client_util, '_resolve_python_command_for_source_bundle', lambda: [sys.executable])
    monkeypatch.setattr(client_util, 'get_runtime_root', lambda: str(tmp_path))

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=54321)

    monkeypatch.setattr(popen_module, 'Popen', spawn)
    log = tmp_path / 'handoff.log'
    handoff.spawn_handoff({'mode': 'bind'}, log_path=str(log))
    assert len(calls) == 1
    assert json.loads(calls[0][0][-1])['log_path'] == str(log)
    assert log.exists()


def test_bind_handoff_reaps_zombie_old_process(monkeypatch):
    from client.update import handoff
    import psutil
    monkeypatch.setattr(handoff, 'is_process_alive', lambda pid: True)
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(status=lambda: psutil.STATUS_ZOMBIE))
    assert not handoff._still_running(54321)
    handoff.wait_for_old_process(54321, timeout=.01)


def test_update_accepts_renamed_python_bundle_from_builder_metadata(tmp_path, monkeypatch):
    """Artifact identity comes from the canonical builder, not its filename."""
    import hashlib
    import shutil
    import zipfile
    from core.agent_build_contract import AgentBuilderKind

    source_zip = tmp_path / 'source.zip'
    with zipfile.ZipFile(source_zip, 'w') as archive:
        archive.writestr('rchclient.py', 'print("source bundle")\n')
    digest = hashlib.sha256(source_zip.read_bytes()).hexdigest()
    releases = tmp_path / 'releases'
    downloads = tmp_path / 'downloads'
    releases.mkdir()
    downloads.mkdir()
    monkeypatch.setattr(preparation, 'get_client_bundle_release_dir', lambda: str(releases))
    monkeypatch.setattr(preparation, 'get_client_bundle_download_dir', lambda: str(downloads))

    def download(_url, target, **_kwargs):
        shutil.copyfile(source_zip, target)

    command = SimpleNamespace(
        client_api=SimpleNamespace(
            build_agent_bundle=lambda *_args, **_kwargs: {
                'builder': AgentBuilderKind.PYTHON.value,
                'file_name': 'custom-source-release.zip',
                'download_url': 'https://example.test/download',
                'sha256': digest,
            },
            download_file=download,
        ),
        emit_progress=lambda *_args, **_kwargs: None,
        _checkpoint=lambda: None,
    )
    installed = preparation.UpdatePreparation(command).run()
    assert Path(installed).read_text() == 'print("source bundle")\n'
    assert Path(installed).parent.name == 'custom-source-release'
    assert list(downloads.iterdir()) == []


@pytest.mark.parametrize('builder,filename', [
    ('go', 'arbitrary.zip'),
    ('invalid-builder', 'arbitrary.zip'),
    (None, 'arbitrary.zip'),
    ('python', '../outside.zip'),
    ('python', r'folder\\outside.zip'),
    ('python', '.hidden.zip'),
    ('python', '..'),
])
def test_update_rejects_wrong_builder_or_unsafe_output_path(tmp_path, monkeypatch, builder, filename):
    from core.agent_build_contract import AgentBuilderKind
    monkeypatch.setattr(preparation, 'get_client_bundle_release_dir', lambda: str(tmp_path))
    def not_download(*_args, **_kwargs):
        raise AssertionError('Invalid metadata must be rejected before any download')
    cmd = SimpleNamespace(
        client_api=SimpleNamespace(
            build_agent_bundle=lambda *_args, **_kwargs: {
                'builder': builder, 'file_name': filename, 'download_url': '/agent.zip',
            },
            download_file=not_download,
        ),
        emit_progress=lambda *_args, **_kwargs: None,
    )
    with pytest.raises(ValueError):
        preparation.UpdatePreparation(cmd).run()
