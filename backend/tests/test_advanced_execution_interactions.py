"""Regression tests for opt-in options, secret, preview gates and safe process targeting."""
import ast
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.application.execution.interaction_broker import InteractionBroker
from server.application.tasks.task_store import WebTaskStore
from server.application.command.advanced_builtin_support import AdvancedBuiltinSupport
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from client.runtime.sdk import interactions


class Events:
    def __init__(self):
        self.events = []
        self.ready = threading.Event()

    def publish(self, event, payload, target_tab_id=''):
        self.events.append((event, payload))
        self.ready.set()


def case():
    bus, store = Events(), WebTaskStore()
    task = store.create_task('client-A', 'test', tab_id='tab-A')
    return InteractionBroker(bus, store), bus, task


def start(broker, task, **kwargs):
    result = {}
    def go():
        result.update(broker.request(task_id=task['task_id'], client_id='client-A',
                                     tab_id='tab-A', message='choose', **kwargs))
    worker = threading.Thread(target=go, daemon=True)
    worker.start()
    return result, worker


def test_select_requires_options_and_enforces_membership():
    broker, bus, task = case()
    with pytest.raises(ValueError, match='requires'):
        broker.request(task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
                       kind='select', message='choose')
    result, worker = start(broker, task, kind='select', options=['a', 'b'])
    assert bus.ready.wait(1)
    request = bus.events[0][1]
    assert request['options'] == ['a', 'b']
    with pytest.raises(ValueError, match='offered'):
        broker.answer(request['interaction_id'], approved=True, value='evil')
    assert worker.is_alive()
    broker.answer(request['interaction_id'], approved=True, value='b')
    worker.join(2)
    assert result['status'] == 'answered' and result['value'] == 'b'


def test_select_rejects_duplicate_options_and_times_out():
    broker, bus, task = case()
    with pytest.raises(ValueError, match='unique'):
        broker.request(task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
                       kind='select', message='x', options=['x', 'x'])
    answer = broker.request(task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
                            kind='select', message='x', options=['a'], timeout_seconds=1)
    assert answer['status'] == 'expired'


def test_secret_not_published_and_rejected_input_discarded():
    broker, bus, task = case()
    result, worker = start(broker, task, kind='secret')
    assert bus.ready.wait(1)
    request = bus.events[0][1]
    broker.answer(request['interaction_id'], approved=True, value='sample-private-value')
    worker.join(2)
    assert result['value'] == 'sample-private-value'
    assert 'sample-private-value' not in repr(bus.events)


def test_client_sdk_select_roundtrip(monkeypatch):
    recorded = []
    class Client:
        def post_data(self, path, **kwargs):
            recorded.append(kwargs['json'])
            return {'status': 'answered', 'value': 'second'}
    monkeypatch.setattr(interactions, 'ClientApiClient', Client)
    monkeypatch.setattr(interactions.context, 'get_script_grant_token', lambda: 'grant')
    monkeypatch.setattr(interactions.context, 'get_command_id', lambda: 42)
    assert interactions.select('Pick', ['first', 'second']) == 'second'
    assert recorded[0]['kind'] == 'select'
    assert recorded[0]['options'] == ['first', 'second']


def test_existing_client_kill_process_not_shadowed():
    assert not hasattr(BuiltinCommandHandler, 'kill_process')
    assert hasattr(BuiltinCommandHandler, 'kill_process_preview')
    assert hasattr(BuiltinCommandHandler, 'kill_by_port')


def test_process_arguments_and_preview():
    parse = AdvancedBuiltinSupport._parse_process_args
    assert parse('--pid 234 --name test -9', by_port=False) == {'pid': 234, 'name': 'test', 'force': True}
    assert parse('--port 8080 --force', by_port=True) == {'port': 8080, 'force': True}
    with pytest.raises(ValueError):
        parse('--port 0', by_port=True)
    with pytest.raises(ValueError):
        parse('--pid 1', by_port=False)
    with pytest.raises(ValueError):
        parse('--pid 22 --pid 23', by_port=False)


def example_row():
    return {'pid': 2324, 'ppid': 12, 'name': 'app', 'user': 'alice',
            'exec_path': '/usr/local/bin/python', 'cmdline': ['python', 'app.py'],
            'cwd': '/tmp', 'status': 'running', 'created_at': 2342.3,
            'memory_rss': 6500, 'threads': 3,
            'listening': [{'port': 8080, 'address': '127.0.0.1', 'protocol': 'tcp'}]}


def test_process_refusal_never_sends_signal():
    calls = []
    class Interactions:
        def confirm(self, message, **kwargs):
            assert 'Executable: /usr/local/bin/python' in message
            return False
    support = AdvancedBuiltinSupport(SimpleNamespace(), Interactions(), None)
    def remote(args):
        calls.append(args)
        return {'processes': [example_row()]}
    support._remote = remote
    output = list(support.kill('--port 8080', by_port=True))
    assert len(calls) == 1 and calls[0]['action'] == 'inspect'
    assert output[-1][0] == 0


def test_process_approval_executes_with_verified_snapshot():
    calls = []
    class Interactions:
        def confirm(self, message, **kwargs):
            return True
    support = AdvancedBuiltinSupport(SimpleNamespace(), Interactions(), None)
    def remote(args):
        calls.append(args)
        return {'processes': [example_row()]} if args['action'] == 'inspect' else {'pid': 2324, 'signal': 'SIGTERM'}
    support._remote = remote
    output = list(support.kill('--pid 2324'))
    assert output[-1][0] == 1
    assert calls[1]['action'] == 'terminate'
    assert calls[1]['expected_name'] == 'app'
    assert calls[1]['created_at'] == 2342.3
    assert calls[1]['force'] is False


def test_disconnection_refusal_preserves_connection():
    events = []
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='client-A', hostname='host'),
                           close=lambda: events.append('closed'))
    support = AdvancedBuiltinSupport(conn, SimpleNamespace(confirm=lambda *a, **kw: False), None)
    result = list(support.disconnect())
    assert result[-1][0] == 0 and not events


def test_plan_script_separate_and_metadata_declares_grants():
    root = Path(__file__).resolve().parents[1] / 'server/resources/scripts/mac/recon'
    original = root / 'personal_mac_backup.py'
    preview = root / 'personal_mac_backup_preview.py'
    assert original.is_file() and preview.is_file()
    source = preview.read_text()
    tree = ast.parse(source)
    definition = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'SCRIPT_METADATA' for t in node.targets))
    meta = ast.literal_eval(definition)
    assert meta['name'] == 'mac/recon/personal_mac_backup_preview'
    assert 'interactions:request' in meta['api_grants'] and 'scripts:read' in meta['api_grants']
    assert 'path_list' in [arg['type'] for arg in meta['params']]
    assert source.index('scan_plan(selected, today)') < source.index('context.confirm(summary') < source.index('artifact.save(')


def test_backup_preview_reject_does_not_create_artifact(tmp_path, monkeypatch):
    import runpy
    path = Path(__file__).resolve().parents[1] / 'server/resources/scripts/mac/recon/personal_mac_backup_preview.py'
    scope = runpy.run_path(str(path), run_name='test_execution')
    folder = tmp_path / 'Docs'
    folder.mkdir()
    (folder / 'memo.txt').write_text('hello')
    (folder / '.hidden').write_text('hidden')
    (folder / '._memo.txt').write_text('resource fork')
    params = {name: False for name in ('include_zshrc', 'include_zsh_history',
                                       'include_chrome_bookmarks', 'include_homebrew', 'include_installed_apps')}
    params['documents'] = [{'path': str(folder), 'enabled': True}]
    params['projects'] = []
    messages = []
    monkeypatch.setattr(scope['context'], 'progress', lambda value, **kw: messages.append(value))
    monkeypatch.setattr(scope['context'], 'confirm', lambda *a, **kw: False)
    monkeypatch.setattr(scope['artifact'], 'save', lambda *a, **kw: pytest.fail('Artifact must not upload after rejection'))
    result = scope['main'](params)
    assert result['uploaded'] is False
    assert any('1 files' in m for m in messages)


def test_backup_preview_approves_exact_filtered_plan(tmp_path, monkeypatch):
    import runpy
    import zipfile
    path = Path(__file__).resolve().parents[1] / 'server/resources/scripts/mac/recon/personal_mac_backup_preview.py'
    scope = runpy.run_path(str(path), run_name='test_execution')
    folder = tmp_path / 'Source'
    folder.mkdir()
    (folder / 'main.py').write_text('print(42)')
    (folder / 'bad.out').write_text('discard')
    (folder / 'node_modules').mkdir()
    (folder / 'node_modules' / 'dep.js').write_text('dependency')
    params = {name: False for name in ('include_zshrc', 'include_zsh_history',
                                       'include_chrome_bookmarks', 'include_homebrew', 'include_installed_apps')}
    params['documents'] = []
    params['projects'] = [{'path': str(folder), 'enabled': True}]
    seen = {}
    def save(file_path, **kwargs):
        with zipfile.ZipFile(file_path) as archive:
            seen['entries'] = archive.namelist()
            seen['contents'] = [archive.read(x) for x in seen['entries']]
        return {'artifact_id': 'mock-artifact'}
    monkeypatch.setattr(scope['context'], 'progress', lambda *args, **kwargs: None)
    monkeypatch.setattr(scope['context'], 'confirm', lambda *a, **kw: True)
    monkeypatch.setattr(scope['artifact'], 'save', save)
    result = scope['main'](params)
    assert result['uploaded'] is True
    assert sum('/main.py' in x for x in seen['entries']) == 1
    assert not any('bad.out' in x or 'dep.js' in x for x in seen['entries'])
    assert any('manifest/' in x for x in seen['entries'])


def test_backup_source_mutation_after_preview_skipped(tmp_path, monkeypatch):
    import runpy
    path = Path(__file__).resolve().parents[1] / 'server/resources/scripts/mac/recon/personal_mac_backup_preview.py'
    scope = runpy.run_path(str(path), run_name='test_execution')
    folder = tmp_path / 'Docs'
    folder.mkdir()
    file = folder / 'keep.txt'
    file.write_text('before')
    params = {name: False for name in ('include_zshrc', 'include_zsh_history',
                                       'include_chrome_bookmarks', 'include_homebrew', 'include_installed_apps')}
    params.update(documents=[{'path': str(folder), 'enabled': True}], projects=[])
    def approve(*args, **kwargs):
        file.write_text('after')
        return True
    monkeypatch.setattr(scope['context'], 'progress', lambda *a, **kw: None)
    monkeypatch.setattr(scope['context'], 'confirm', approve)
    monkeypatch.setattr(scope['artifact'], 'save', lambda *a, **kw: pytest.fail('Do not upload empty verified snapshot'))
    result = scope['main'](params)
    assert result['uploaded'] is False


def test_remote_process_rejects_pid_reuse_before_signal(monkeypatch, capsys):
    import sys
    from server.application.command.process_control_client_source import PROCESS_CONTROL_SOURCE
    signals = []
    class FakeProc:
        pid = 2324
        def create_time(self): return 200.0
        def name(self): return 'app'
        def exe(self): return '/usr/bin/app'
        def terminate(self): signals.append('SIGTERM')
        def kill(self): signals.append('SIGKILL')
    class FakePsutil:
        class Error(Exception): pass
        class NoSuchProcess(Error): pass
        class ZombieProcess(Error): pass
        class AccessDenied(Error): pass
        def Process(self, pid): return FakeProc()
    monkeypatch.setitem(sys.modules, 'psutil', FakePsutil())
    exec(PROCESS_CONTROL_SOURCE, {'kwargs': {
        'action': 'terminate', 'pid': 2324, 'created_at': 100.0,
        'expected_name': 'app', 'expected_exe': '/usr/bin/app', 'force': True,
    }})
    text = capsys.readouterr().out
    response = json.loads(text.split('__RCH_PROCESS_CONTROL_RESULT__:')[1])
    assert not response['ok'] and 'identity changed' in response['error']
    assert not signals


def test_remote_process_graceful_signal_only_after_identity_verified(monkeypatch, capsys):
    import sys
    from server.application.command.process_control_client_source import PROCESS_CONTROL_SOURCE
    signals = []
    class FakeProc:
        pid = 2324
        def create_time(self): return 100.0
        def name(self): return 'app'
        def exe(self): return '/usr/bin/app'
        def terminate(self): signals.append('SIGTERM')
        def kill(self): signals.append('SIGKILL')
    class FakePsutil:
        class Error(Exception): pass
        class NoSuchProcess(Error): pass
        class ZombieProcess(Error): pass
        class AccessDenied(Error): pass
        def Process(self, pid): return FakeProc()
    monkeypatch.setitem(sys.modules, 'psutil', FakePsutil())
    exec(PROCESS_CONTROL_SOURCE, {'kwargs': {
        'action': 'terminate', 'pid': 2324, 'created_at': 100.0,
        'expected_name': 'app', 'expected_exe': '/usr/bin/app', 'force': False,
    }})
    response = json.loads(capsys.readouterr().out.split('__RCH_PROCESS_CONTROL_RESULT__:')[1])
    assert response['ok'] and signals == ['SIGTERM']


def test_process_interactive_pid_prompt_still_requires_approval():
    calls = []
    class Interactions:
        def select(self, *args, **kwargs): return 'PID'
        def ask(self, *args, **kwargs): return '2324'
        def confirm(self, *args, **kwargs): return False
    support = AdvancedBuiltinSupport(SimpleNamespace(), Interactions(), None)
    def remote(args):
        calls.append(args)
        return {'processes': [example_row()]}
    support._remote = remote
    result = list(support.kill())
    assert calls == [{'force': False, 'pid': 2324, 'action': 'inspect'}]
    assert result[-1][0] == 0


def test_process_interactive_port_prompt_still_requires_approval():
    calls = []
    class Interactions:
        def ask(self, *args, **kwargs): return '8080'
        def confirm(self, *args, **kwargs): return False
    support = AdvancedBuiltinSupport(SimpleNamespace(), Interactions(), None)
    def remote(args):
        calls.append(args)
        return {'processes': [example_row()]}
    support._remote = remote
    result = list(support.kill(by_port=True))
    assert calls == [{'force': False, 'port': 8080, 'action': 'inspect'}]
    assert result[-1][0] == 0
