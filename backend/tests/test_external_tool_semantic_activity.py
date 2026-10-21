"""Manager actions use post-dispatch semantic Activity without serializing payloads."""
import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import threading
import uuid

import pytest

from server.application.web.external_tool_client_lifecycle_api import WebExternalToolClientLifecycleApi
from server.application.external_tools.external_tool_client_runtime import ExternalToolClientLifecycleRuntime


class Quick:
    def discard(self, entry_id):
        pass
    def finish(self, entry_id, status):
        pass


class MemoryStore:
    def __init__(self):
        self.entries = {}
        self.quick_store = Quick()
        self.write_service = self

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat()

    def create_activity_for_dispatch(self, conn, activity_id, pending):
        assert activity_id not in self.entries
        self.entries[activity_id] = {
            'kind': pending['kind'], 'action': pending['action'], 'origin': pending['origin'],
            'invocation': pending['invocation'], 'resolved': pending['resolved'],
            'status': 'running', 'outputs': [], 'machine_id': conn.session_info.machine_id,
        }

    def append_output_for_connection(self, conn, entry_id, status, text, eof=0):
        if entry_id in self.entries:
            self.entries[entry_id]['outputs'].append(text)

    def update_entry_status_for_connection(self, conn, entry_id, status, cwd_end=''):
        if entry_id in self.entries:
            self.entries[entry_id]['status'] = status


def make_orchestrator(store):
    policy_source = (Path(__file__).parents[1] / 'server/application/history/history_record_policy.py').read_text()
    policy_tree = ast.parse(policy_source)
    policy_cls = next(node for node in policy_tree.body if isinstance(node, ast.ClassDef) and node.name == 'CommandHistoryRecordPolicy')
    policy_ns = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[policy_cls], type_ignores=[])), '<record-policy>', 'exec'), policy_ns)
    source = (Path(__file__).parents[1] / 'server/application/history/history_orchestrator.py').read_text()
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'CommandHistoryOrchestrator')
    fake = SimpleNamespace()
    namespace = {'threading': threading, 'uuid': uuid,
                 'CommandHistoryRecordPolicy': policy_ns['CommandHistoryRecordPolicy'], 'QuickHistoryRecordPolicy': fake}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<orchestrator>', 'exec'), namespace)
    return namespace['CommandHistoryOrchestrator'](store)


class Runtime:
    def __init__(self, orchestrator, *, result=None, failure=''):
        self.orchestrator = orchestrator
        self.result = result
        self.failure = failure
        self.conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='machine-a', client_id='client-a'))
        self.calls = []
        self.core = SimpleNamespace(remote_execution_service=SimpleNamespace(
            history_orchestrator=orchestrator, get_connection=lambda client_id: self.conn,
        ))
        self.client_lifecycle_runtime = self

    def __getattr__(self, name):
        def run(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if self.failure == 'before':
                raise ValueError('PRE-SEND secret payload')
            entry_id = kwargs.get('history_entry_id')
            if not entry_id:
                return self.result
            self.orchestrator.confirm_dispatch(self.conn, entry_id, 'external_tool_oneshot __json__:SECRET', 'command')
            if self.failure == 'after':
                raise RuntimeError('POST-SEND secret payload')
            return self.result
        return run


def setup(result=None, failure=''):
    store = MemoryStore()
    orch = make_orchestrator(store)
    runtime = Runtime(orch, result=result, failure=failure)
    return store, orch, runtime, WebExternalToolClientLifecycleApi(None, runtime)


CASES = [
    ('install_client_tool', 'install_package', 'install', {'installed': True}, 'package-a'),
    ('uninstall_client_tool', 'uninstall_package', 'uninstall', {'installed': False}, 'package-a'),
    ('clear_client_package_cache', 'clear_package_cache', 'clear-cache', {'cache': {}, 'cache_removed': False}, 'package-a'),
    ('start_client_instance', 'start_instance', 'start', {'running': True}, 'tool-a'),
    ('run_client_oneshot', 'run_oneshot', 'oneshot', {'success': True, 'returncode': 0, 'stdout': 'PASSWORD=secret'}, 'tool-a'),
    ('stop_client_instance', 'stop_instance', 'stop', {'running': False}, 'tool-a'),
    ('remove_client_instance', 'remove_instance', 'remove', {'removed': True}, 'tool-a'),
    ('clear_client_logs', 'clear_instance_logs', 'clear-logs', {'cleared': True}, 'tool-a'),
]


@pytest.mark.parametrize('method,action,_,result,target', CASES)
def test_eight_operations_are_one_safe_entry(method, action, _, result, target):
    store, orch, runtime, api = setup(result)
    kwargs = ({'instance_id': 'instance-a'} if method in ('start_client_instance', 'stop_client_instance', 'remove_client_instance', 'clear_client_logs') else {})
    kwargs.update({'params': {'secret': 'TOKEN'}} if method not in ('remove_client_instance','clear_client_logs') else {})
    output = getattr(api, method)('client-a', target, origin='web_ui', **kwargs)
    assert output == result
    assert len(store.entries) == 1
    entry = next(iter(store.entries.values()))
    assert entry['kind'] == 'external_tool' and entry['action'] == action
    assert entry['origin'] == 'web_ui' and entry['status'] == 'success'
    assert entry['machine_id'] == 'machine-a'
    assert len(entry['outputs']) == 1
    assert 'TOKEN' not in str(entry) and 'PASSWORD' not in str(entry) and '__json__' not in str(entry)
    assert entry['resolved'] == {'command_type': 'command'}
    assert not orch._pending
    assert runtime.calls[0][2]['history_entry_id']


@pytest.mark.parametrize('result,expected', [
    ({'success': False, 'returncode': 4, 'stderr': 'secret'}, 'error'),
    ({'success': False, 'returncode': 1, 'timed_out': True}, 'timed_out'),
])
def test_oneshot_status_and_no_stdout_or_stderr(result, expected):
    store, orch, _, api = setup(result)
    api.run_client_oneshot('client-a', 'tool-a', params={'key':'my-credential'})
    entry = next(iter(store.entries.values()))
    assert entry['status'] == expected
    assert entry['origin'] == 'web_api'
    assert 'secret' not in str(entry) and 'my-credential' not in str(entry)


@pytest.mark.parametrize('failure,count', [('before', 0), ('after', 1)])
def test_transport_failure_is_recorded_only_after_dispatch(failure, count):
    store, orch, _, api = setup(failure=failure)
    with pytest.raises((ValueError, RuntimeError)):
        api.run_client_oneshot('client-a', 'tool-a', params={'token':'do-not-save'})
    assert len(store.entries) == count
    assert not orch._pending
    if count:
        entry = next(iter(store.entries.values()))
        assert entry['status'] == 'error'
        assert 'secret' not in str(entry) and 'do-not-save' not in str(entry)


def test_read_only_web_methods_do_not_record_activity():
    store, orch, runtime, api = setup({'items': []})
    api.status_client_instance('client-a', 'tool-a', 'instance-a')
    api.list_client_instances('client-a', 'tool-a')
    api.resolve_client_launcher('client-a', 'tool-a')
    api.preview_client_instance_command('client-a', 'tool-a')
    assert not store.entries and not orch._pending
    assert all('history_entry_id' not in call[2] for call in runtime.calls)


def test_unknown_result_is_not_misreported_success():
    store, _, _, api = setup({'message': 'ok'})
    api.start_client_instance('client-a', 'tool-a')
    assert next(iter(store.entries.values()))['status'] == 'error'


def test_real_client_lifecycle_dispatch_forwards_activity_identity_without_changing_task_type():
    forwarded = []
    runner = SimpleNamespace(run_foreground_json_command=lambda client_id, command, **kwargs: (
        forwarded.append((client_id, command, kwargs)) or {'success': True}))
    stub = SimpleNamespace(remote_execution_service=runner)
    result = ExternalToolClientLifecycleRuntime._run_client_lifecycle_command(
        stub, 'client-a', 'external_tool_oneshot __json__:raw', history_entry_id='semantic-entry')
    assert result == {'success': True}
    assert forwarded[0][2] == {'task_type':'external_tool', 'source':'web_external_tool', 'history_entry_id':'semantic-entry'}

def test_derived_instance_is_not_falsely_labeled_default():
    store, _, _, api = setup({'running': True, 'instance_id':'derived-7000'})
    api.start_client_instance('client-a', 'pkg.module', params={'port': 7000})
    entry = next(iter(store.entries.values()))
    assert entry['invocation']['arguments'] == {'tool_id':'pkg.module'}
    assert 'derived-7000' in entry['outputs'][0]
