"""Background Jobs share the active Client connection's HTTP API identity."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from client.http.session_auth import clear_token, get_token
from client.jobs.core.manager import JobManager
from client.jobs.core import subprocess_runner
from client.runtime.sdk.context import get_current_context


def _job_instance():
    return SimpleNamespace(
        client_id='client-1', command_id=7, hostname='host', job_id='job-1',
        job_name='sample', job_key='sample', execution_mode='inproc',
    )


def test_inproc_job_context_inherits_connection_credential():
    manager = JobManager(SimpleNamespace(client_session_token='connected-token'))
    assert manager._build_sdk_context(_job_instance())['client_session_token'] == 'connected-token'


def test_subprocess_job_receives_token_through_environment_not_context_file(tmp_path, monkeypatch):
    import client.jobs.core.manager as module

    socket = SimpleNamespace(client_id='client-1', info={'hostname': 'host'},
                             client_session_token='connected-token')
    manager = JobManager(socket)
    job_path = tmp_path / 'sample.py'
    job_path.write_text('pass\n', encoding='utf-8')
    working = tmp_path / 'job-context'
    calls = []

    class Process:
        pid = 12345
        def wait(self):
            return 0

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    monkeypatch.setattr(manager, '_monitor_subprocess', lambda runtime: None)
    runtime = manager._start_subprocess_job(
        str(job_path), 'sample.py', 7,
        job_metadata={'name': 'sample'}, resolved_params={}, cleanup_path=str(working),
    )
    runtime.thread.join(timeout=2)
    assert calls[0][1]['env']['RCH_CHILD_SESSION_TOKEN'] == 'connected-token'
    data = json.loads((working / 'job_subprocess_context.json').read_text(encoding='utf-8'))
    assert 'client_session_token' not in data
    assert 'connected-token' not in (working / 'job_subprocess_context.json').read_text(encoding='utf-8')


def test_subprocess_runner_imports_session_token_into_sdk_and_clears_environment(monkeypatch):
    clear_token()
    monkeypatch.setenv('RCH_CHILD_SESSION_TOKEN', 'connected-token')
    monkeypatch.setattr(subprocess_runner, '_ensure_backend_on_path', lambda: None)
    monkeypatch.setattr(subprocess_runner, '_parse_args', lambda: SimpleNamespace(context_file='unused'))
    monkeypatch.setattr(subprocess_runner, '_load_context', lambda _: {'client_id': 'client-1'})
    monkeypatch.setattr(subprocess_runner, '_start_control_reader', lambda job: (None, None, None))

    observed = {}
    job = _job_instance()
    job.is_running = False
    def run():
        observed['sdk_token'] = get_current_context().get('client_session_token')
        observed['client_token'] = get_token()
    job.run = run
    monkeypatch.setattr(subprocess_runner, '_load_job_instance', lambda _: job)
    try:
        assert subprocess_runner.main() == 0
        assert observed == {'sdk_token': 'connected-token', 'client_token': 'connected-token'}
        assert 'RCH_CHILD_SESSION_TOKEN' not in __import__('os').environ
    finally:
        clear_token()
