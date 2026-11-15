import json
import ast
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from client.control_registration import build_control_dispatcher
from client.runtime.control_dispatcher import ClientControlDispatcher
from client.runtime.execution.runtime import ExecutionRuntime
from client.remote_files.manager import RemoteFilesManager
from core.protocol.control import (ControlDomain, ControlRequest, ControlValue, JobAction,
                                   RemoteFilesAction, ScriptAction, ClipboardAction,
                                   ExecutionPolicy, control_actions, build_control_message)


def test_every_domain_has_typed_actions_and_matching_client_registration():
    class Manager:
        def execute(self, scope, action, payload):
            assert isinstance(action, ControlValue)
            return 1, str(action)
        def cancel_policy(self, action, payload):
            return 'none'
    manager = Manager()
    files = RemoteFilesManager()
    runtime = SimpleNamespace(execution=ExecutionRuntime(SimpleNamespace()),
        job_manager=manager, remote_files_manager=files, script_manager=manager,
        configuration_manager=manager, process_manager=manager,
        watchdog_control=manager, clipboard_manager=None, session_control=manager)
    dispatch = build_control_dispatcher(runtime)
    try:
        assert {x.value for x in ControlDomain} == {'job','remote_files','script','clipboard','configuration','process','watchdog','session','external_tool'}
        expected = {(domain, action): policy for domain in ControlDomain for action, policy in control_actions(domain)}
        assert set(dispatch._actions) == set(expected)
        for key, policy in expected.items():
            assert dispatch.policy(*key) == policy
            assert dispatch._actions[key].action is key[1]
        assert set(files.actions) == set(RemoteFilesAction)
        assert {a for a, p in control_actions(ControlDomain.REMOTE_FILES) if p is ExecutionPolicy.INDEPENDENT} == set(RemoteFilesAction)
        assert dispatch.execute(1, 'job', 'ps', {}) == (1, 'ps')
        assert dispatch.execute(2, 'clipboard', 'get', {}) == (0, 'Clipboard disabled on Client')
        assert dispatch.execute(3, 'script', 'unknown', {})[0] == 0
        assert dispatch.execute(4, 'not_registered', 'get', {})[0] == 0
        assert dispatch._actions[ControlDomain.SCRIPT, ScriptAction.RUN].cancel_policy is not None
        assert dispatch._actions[ControlDomain.CLIPBOARD, ClipboardAction.SET].cancel_policy == 'cooperative'
    finally:
        dispatch.disconnect()


def test_generic_scheduler_uses_registered_policy_and_callbacks_not_domain_names():
    execution = ExecutionRuntime(SimpleNamespace())
    dispatch = ClientControlDispatcher(execution)
    done = Event()
    seen = []
    def handler(scope, action, payload):
        assert scope.execution_context.get_cancel_policy()['mode'] == 'none'
        return 1, payload
    def prepare(action, payload):
        return {**payload, 'prepared': True}
    def route(data):
        return data['id'], *dispatch.execute(data['id'], data['domain'], data['action'], data['payload'])
    def send(*args):
        seen.append(args)
        done.set()
    try:
        # This unrelated test-only domain is not part of any protocol policy catalog.
        dispatch.register('probe', 'check', handler, policy=ExecutionPolicy.INDEPENDENT,
                          prepare=prepare, cancel_policy='none')
        assert dispatch.policy('probe', 'check') is ExecutionPolicy.INDEPENDENT
        assert dispatch.submit({'id': 10, 'domain': 'probe', 'action': 'check', 'payload': {}}, route, send) is None
        assert done.wait(2)
        assert seen == [(10, 1, {'prepared': True})]
        assert execution.context_store.get_existing(10) is None
    finally:
        dispatch.disconnect()


def test_wire_identity_stays_string_and_requests_resolve_enums():
    request = ControlRequest('job', 'start', {})
    assert request.domain is ControlDomain.JOB and request.action is JobAction.START
    msg = build_control_message(1, request.domain, request.action, request.payload)
    assert type(msg['domain']) is str and type(msg['action']) is str
    assert json.loads(json.dumps(msg)) == {'type': 'control', 'id': 1, 'domain': 'job', 'action': 'start', 'payload': {}}
    with pytest.raises(ValueError):
        ControlRequest('job', 'run', {})


def test_runtime_modules_do_not_import_concrete_control_actions():
    runtime_dir = Path(__file__).resolve().parents[2] / 'client' / 'runtime'
    for file in runtime_dir.rglob('*.py'):
        tree = ast.parse(file.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'core.protocol.control':
                assert {alias.name for alias in node.names} <= {'ExecutionPolicy', 'validate_control_fields'}, file


def test_remote_write_path_snapshot_and_cancelled_lock_wait(tmp_path, monkeypatch):
    import threading
    import time
    from client.runtime.filesystem.mutation_guard import filesystem_mutation
    from client.runtime.execution.context import ExecutionContext, CommandCancelledError
    from client.runtime.execution.scope import ExecutionScope
    from core.protocol.control import RemoteFilesAction

    first = tmp_path / 'first'; first.mkdir()
    second = tmp_path / 'second'; second.mkdir()
    (first / 'source.txt').write_text('original')
    (second / 'source.txt').write_text('untouched')
    manager = RemoteFilesManager()
    monkeypatch.chdir(first)
    payload = manager.prepare_paths(RemoteFilesAction.RENAME_PATH, {'old_path':'source.txt', 'new_path':'target.txt'})
    monkeypatch.chdir(second)
    scope = ExecutionScope(SimpleNamespace(), ExecutionContext(101))
    assert manager.execute(scope, RemoteFilesAction.RENAME_PATH, payload)[0] == 1
    assert (first / 'target.txt').read_text() == 'original'
    assert (second / 'source.txt').read_text() == 'untouched'
    context = ExecutionContext(102)
    context.set_cancel_policy('cooperative')
    cancelled = []
    entered = threading.Event()
    def waiting():
        entered.set()
        try:
            manager.execute(ExecutionScope(SimpleNamespace(), context), RemoteFilesAction.DELETE_PATHS,
                            {'paths':[str(first / 'target.txt')]})
        except CommandCancelledError:
            cancelled.append(True)
    with filesystem_mutation(lambda: None):
        worker = threading.Thread(target=waiting)
        worker.start(); assert entered.wait(2)
        context.request_cancel()
        worker.join(2)
        assert not worker.is_alive()
    assert cancelled == [True]
    assert (first / 'target.txt').exists()


def test_all_requested_policy_changes():
    from core.protocol.control import ConfigurationAction, ProcessAction, WatchdogAction, execution_policy
    expected = {
        ControlDomain.JOB: {JobAction.PS, JobAction.STATUS},
        ControlDomain.REMOTE_FILES: set(RemoteFilesAction),
        ControlDomain.SCRIPT: set(),
        ControlDomain.CLIPBOARD: set(ClipboardAction),
        ControlDomain.CONFIGURATION: {ConfigurationAction.GET},
        ControlDomain.PROCESS: {ProcessAction.KILL},
        ControlDomain.WATCHDOG: {WatchdogAction.STATUS},
    }
    for domain, actions in expected.items():
        assert {a for a, p in control_actions(domain) if p == ExecutionPolicy.INDEPENDENT} == actions
