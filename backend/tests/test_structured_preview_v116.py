"""Regression for kill_by_port's RCH positional grammar and reusable preview."""
import threading
from types import SimpleNamespace

import pytest

from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.services.process import approved_process_service as aps
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.execution.interaction_broker import InteractionBroker
from server.application.tasks.task_store import WebTaskStore
from client.runtime.sdk import interactions


class Events:
    def __init__(self):
        self.events = []
        self.started = threading.Event()

    def publish(self, name, payload, target_tab_id=''):
        self.events.append((name, payload, target_tab_id))
        self.started.set()


def test_port_candidate_and_positional_grammar():
    assert hasattr(CommandProcessMixin.kill_by_port, 'help')
    assert not any(c['name'] == 'kill_by_port' for c in BuiltinCommandHandler.WEB_COMMAND_TEMPLATES)
    from core.utils.parsing import parse as split_command
    assert split_command('kill_by_port 9999') == ('kill_by_port', '9999')
    assert aps.parse_target('9999', by_port=True) == {'force': False, 'port': 9999}
    assert aps.parse_target('9999 -9', by_port=True) == {'force': True, 'port': 9999}
    for bad in ('--port 9999', '9999 8888', '9999 foo', '0', '65536', ''):
        with pytest.raises(aps.ProcessApprovalError):
            aps.parse_target(bad, by_port=True)


def test_port_command_inspects_and_previews_before_signal(monkeypatch):
    previews = []
    class Interactions:
        def __init__(self, owner): pass
        def approve(self, message, preview):
            previews.append(preview)
            return False
    monkeypatch.setattr(aps, 'ClientCommandInteractions', Interactions)
    monkeypatch.setattr(aps, 'find_targets', lambda args: [{
        'pid': 421, 'name': 'server', 'user': 'owner', 'exec_path': '/bin/server',
        'cmdline': ['/bin/server', '9999'], 'cwd': '/tmp', 'ppid': 1,
        'status': 'running', 'created_at': 12.0, 'memory_rss': 128,
        'threads': 2, 'listening': [{'protocol': 'tcp', 'address': '127.0.0.1', 'port': 9999}],
    }])
    monkeypatch.setattr(aps, 'terminate_verified', lambda *a, **k: pytest.fail('must not signal'))
    owner = SimpleNamespace(_set_timeout=lambda t: None, _ensure_not_interrupted=lambda **k: None,
                            _send_interim_result=lambda *a: None)
    status, msg = CommandProcessMixin._run_approved_process_command(owner, '9999', by_port=True)
    assert status == 1 and 'rejected' in msg
    assert previews[0]['summary'][0] == {'label': 'PID', 'value': '421'}
    assert previews[0]['rows'][0]['port'] == '9999'


def test_structured_preview_roundtrip_approve_and_reject():
    events = Events()
    store = WebTaskStore()
    task = store.create_task('client-test', 'demo', tab_id='tab-test')
    broker = InteractionBroker(events, store)
    preview = {'summary': [{'label': 'Files', 'value': '2'}],
               'columns': [{'key': 'path', 'label': 'Path'}],
               'rows': [{'path': 'Documents'}],
               'details': [{'title': 'Full plan', 'content': 'memo.txt'}],
               'notice': 'Review before continuing'}
    for approve in (False, True):
        results = []
        thread = threading.Thread(target=lambda: results.append(broker.request(
            task_id=task['task_id'], client_id='client-test', tab_id='tab-test',
            kind='preview', message='Review', preview=preview, timeout_seconds=10)), daemon=True)
        events.started.clear()
        thread.start()
        assert events.started.wait(1)
        request = next(data for name, data, tab in reversed(events.events) if name == 'interaction_requested')
        assert request['preview'] == preview
        assert broker.pending('tab-test')[0]['preview'] == preview
        broker.answer(request['interaction_id'], approved=approve)
        thread.join(2)
        assert not thread.is_alive()
        assert results[0]['value'] is approve
    assert broker.pending('tab-test') == []


def test_preview_validation_is_text_only_and_bounded():
    norm = InteractionBroker._normalize_preview
    with pytest.raises(ValueError):
        norm({'html': '<script>alert(1)</script>'})
    with pytest.raises(ValueError):
        norm({'columns': [{'key': 'name', 'label': 'Name'}], 'rows': [{'other': 'x'}]})
    with pytest.raises(ValueError):
        norm({'columns': [{'key': 'name', 'label': 'Name'}], 'rows': [{'name': 'x'}] * 101})
    with pytest.raises(ValueError):
        norm({'summary': 'not-a-list'})
    assert norm({'summary': [], 'columns': [], 'rows': [], 'details': []})['notice'] == ''


def test_sdk_preview_passes_structured_plan_and_protects_rejection(monkeypatch):
    payloads = []
    class Client:
        def post_data(self, path, **kwargs):
            payloads.append(kwargs['json'])
            return {'status': 'rejected', 'value': False}
    monkeypatch.setattr(interactions, 'ClientApiClient', Client)
    monkeypatch.setattr(interactions.context, 'get_script_grant_token', lambda: 'grant')
    monkeypatch.setattr(interactions.context, 'get_command_id', lambda: 1)
    assert not interactions.approve_preview('Review', {'summary': [], 'columns': [], 'rows': []})
    assert payloads[0]['kind'] == 'preview'
    assert payloads[0]['preview']['summary'] == []


def test_harmless_preview_builtin_does_not_modify_files():
    handler = object.__new__(BuiltinCommandHandler)
    handler.interactions = SimpleNamespace(approve_preview=lambda *args, **kwargs: True)
    assert list(handler.interaction_preview_demo()) == [(1, 'Preview demo result: approved; no action executed.')]
