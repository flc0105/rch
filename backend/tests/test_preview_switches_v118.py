"""Optional preview switches, fail-closed approval and Server builtin ownership."""
import threading
import time
from types import SimpleNamespace

import pytest

from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.services.process import approved_process_service as aps
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.execution.interaction_broker import InteractionBroker
from server.application.tasks.task_store import WebTaskStore


class Events:
    def __init__(self):
        self.ready = threading.Event()
        self.events = []

    def publish(self, kind, data, target_tab_id=''):
        self.events.append((kind, data, target_tab_id))
        if kind == 'interaction_requested':
            self.ready.set()


def preview():
    return aps.build_preview({
        'pid': 2233, 'name': 'example', 'user': 'user', 'exec_path': '/usr/bin/example',
        'created_at': 1.0, 'cmdline': ['/usr/bin/example'], 'cwd': '/tmp',
        'ppid': 1, 'status': 'running', 'memory_rss': 100, 'threads': 1,
        'listening': [{'protocol': 'tcp', 'address': '127.0.0.1', 'port': 8080}],
    }, port=8080)


def test_preview_switch_schema_is_optional_and_strict():
    normal = InteractionBroker._normalize_preview({'summary': [], 'columns': [], 'rows': [], 'details': []})
    assert 'switches' not in normal
    enriched = InteractionBroker._normalize_preview(preview())
    assert enriched['switches'] == [{
        'key': 'force', 'label': 'Force termination (SIGKILL / -9)',
        'description': 'Disabled: SIGTERM. Enabled: immediate SIGKILL; no graceful shutdown.',
        'default': False,
    }]
    for switches in (
        [{'key': 'force', 'label': 'Force', 'default': 'yes'}],
        [{'key': 'force', 'label': 'Force'}, {'key': 'force', 'label': 'Again'}],
        [{'key': 'force', 'label': 'Force', 'html': '<img>'}],
        [{'key': 'bad-key', 'label': 'Force'}],
        'force',
    ):
        with pytest.raises(ValueError):
            InteractionBroker._normalize_preview({'switches': switches})


@pytest.mark.parametrize('approve,force', [(True, False), (True, True), (False, None)])
def test_broker_round_trip_validated_switches(approve, force):
    events = Events()
    store = WebTaskStore()
    task = store.create_task('client-A', 'kill_port 8080', tab_id='tab-A')
    broker = InteractionBroker(events, store)
    result = []
    worker = threading.Thread(target=lambda: result.append(broker.request(
        task_id=task['task_id'], client_id='client-A', tab_id='tab-A',
        kind='preview', message='Kill process?', preview=preview(), timeout_seconds=5)), daemon=True)
    worker.start()
    assert events.ready.wait(2)
    offered = events.events[-1][1]
    assert offered['preview']['switches'][0]['default'] is False
    assert broker.pending('tab-A')[0]['preview']['switches'] == offered['preview']['switches']
    if approve:
        for forged in ({'force': 'true'}, {'force': 1}, {}, {'force': False, 'extra': True}, True, None):
            with pytest.raises(ValueError, match='switch'):
                broker.answer(offered['interaction_id'], approved=True, value=forged)
        assert worker.is_alive(), 'invalid input must not release waiting task'
    broker.answer(offered['interaction_id'], approved=approve, value={'force': force} if approve else None)
    worker.join(2)
    assert not worker.is_alive()
    assert result[0]['status'] == ('answered' if approve else 'rejected')
    assert result[0]['value'] == ({'force': force} if approve else False)


def test_client_process_signal_only_follows_approved_switch(monkeypatch):
    rows = [{'pid': 2233, 'name': 'example', 'user': 'user', 'exec_path': '/usr/bin/example',
             'created_at': 1.0, 'cmdline': [], 'cwd': '/tmp', 'ppid': 1, 'status': 'running',
             'memory_rss': 0, 'threads': 1, 'listening': []}]
    monkeypatch.setattr(aps, 'find_targets', lambda criteria: rows)
    calls = []
    monkeypatch.setattr(aps, 'terminate_verified', lambda row, **kw: (calls.append(kw),
                           'SIGKILL' if kw['force'] else 'SIGTERM')[1])
    owner = SimpleNamespace(_set_timeout=lambda *a: None,
                            _checkpoint=lambda **kw: None,
                            _send_interim_result=lambda *a: None)
    for reply in (None, {'force': False}, {'force': True}):
        monkeypatch.setattr(aps.ClientCommandInteractions, 'approve', lambda *a, **kw: reply)
        status, text = CommandProcessMixin._run_approved_process_command(owner, '8080', by_port=True)
        assert status == 1
        if reply is None:
            assert 'rejected' in text
        else:
            assert ('SIGKILL' if reply['force'] else 'SIGTERM') in text
    assert calls == [{'force': False, 'port': 8080}, {'force': True, 'port': 8080}]


def test_disconnect_stays_server_builtin_and_client_commands_do_not_shadow_it():
    assert any(x['name'] == 'disconnect' and x['source'] == 'server'
               for x in BuiltinCommandHandler.WEB_COMMAND_TEMPLATES)
    assert hasattr(BuiltinCommandHandler, 'disconnect')
    assert not hasattr(CommandProcessMixin, 'disconnect')
    from server.application.command.advanced_builtin_support import AdvancedBuiltinSupport
    closed = []
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='client-A', hostname='test'),
                           close=lambda: closed.append(True))
    result = list(AdvancedBuiltinSupport(conn, SimpleNamespace(confirm=lambda *a, **k: False)).disconnect())
    assert result[-1][0] == 0 and not closed


def test_approved_server_disconnect_sends_client_kill_connection():
    from server.application.command.advanced_builtin_support import AdvancedBuiltinSupport
    sent = []

    def send_command(command):
        sent.append(command)
        yield 0, None

    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='client-A', hostname='test'),
                           send_command=send_command,
                           close=lambda: pytest.fail('Do not directly close Server transport'))
    result = list(AdvancedBuiltinSupport(conn, SimpleNamespace(confirm=lambda *a, **kw: True)).disconnect())
    assert result[-1] == (1, 'Client connection closed.')
    assert sent == ['kill_connection']


@pytest.mark.parametrize('by_port,arg,criteria', [
    (True, '9999', {'port': 9999}),
    (True, '9999 -9', {'port': 9999, 'force': True}),
    (False, '30565', {'pid': 30565}),
    (False, '30565 -9', {'pid': 30565, 'force': True}),
    (False, 'python3', {'name': 'python3'}),
    (False, 'python3 -9', {'name': 'python3', 'force': True}),
    (False, "'a name' -9", {'name': 'a name', 'force': True}),
])
def test_command_line_force_is_only_preview_default(by_port, arg, criteria):
    assert aps.parse_target(arg, by_port=by_port) == criteria
    offered = aps.build_preview(preview_process_row(), force_default=criteria.get('force', False))
    assert offered['switches'][0]['default'] == criteria.get('force', False)
    expected_initial = 'SIGKILL' if criteria.get('force') else 'SIGTERM'
    assert any(entry['value'] == expected_initial for entry in offered['summary'])


def preview_process_row():
    return {
        'pid': 2233, 'name': 'example', 'user': 'user', 'exec_path': '/usr/bin/example',
        'created_at': 1.0, 'cmdline': [], 'cwd': '/tmp', 'ppid': 1, 'status': 'running',
        'memory_rss': 100, 'threads': 1, 'listening': [],
    }


@pytest.mark.parametrize('bad,by_port', [
    ('9999 -9 -9', True), ('-9', True), ('9999 --force', True),
    ('9999 -9 other', True), ('--port 9999 -9', True),
    ('python3 --force', False), ('-9', False), ('30565 -9 -9', False),
    ('--pid 30565 -9', False),
])
def test_force_syntax_rejects_unexpected_arguments(bad, by_port):
    with pytest.raises(aps.ProcessApprovalError):
        aps.parse_target(bad, by_port=by_port)


@pytest.mark.parametrize('argument,force_initial,user_force,signal', [
    ('9999', False, False, 'SIGTERM'),
    ('9999', False, True, 'SIGKILL'),
    ('9999 -9', True, True, 'SIGKILL'),
    ('9999 -9', True, False, 'SIGTERM'),
])
def test_approved_ui_switch_overrides_cli_default(monkeypatch, argument, force_initial, user_force, signal):
    offered = []
    calls = []
    monkeypatch.setattr(aps, 'find_targets', lambda criteria: [preview_process_row()])

    def approve(ui, message, preview):
        offered.append(preview)
        return {'force': user_force}

    monkeypatch.setattr(aps.ClientCommandInteractions, 'approve', approve)
    monkeypatch.setattr(aps, 'terminate_verified', lambda row, **kwargs: (
        calls.append(kwargs), 'SIGKILL' if kwargs['force'] else 'SIGTERM')[1])
    host = SimpleNamespace(
        _set_timeout=lambda *a: None,
        _checkpoint=lambda **kw: None,
        _send_interim_result=lambda *a: None,
    )
    result, text = CommandProcessMixin._run_approved_process_command(host, argument, by_port=True)
    assert result == 1 and signal in text
    assert offered[0]['switches'][0]['default'] is force_initial
    assert calls == [{'force': user_force, 'port': 9999}]


def test_trailing_force_never_bypasses_approval(monkeypatch):
    monkeypatch.setattr(aps, 'find_targets', lambda criteria: [preview_process_row()])
    monkeypatch.setattr(aps.ClientCommandInteractions, 'approve', lambda *a, **k: None)
    monkeypatch.setattr(aps, 'terminate_verified', lambda *a, **k: pytest.fail('No approval, no signal'))
    host = SimpleNamespace(_set_timeout=lambda *a: None,
                           _checkpoint=lambda **kw: None,
                           _send_interim_result=lambda *a: None)
    result, message = CommandProcessMixin._run_approved_process_command(host, '9999 -9', by_port=True)
    assert result == 1 and 'rejected' in message
