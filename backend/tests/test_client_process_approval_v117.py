"""Client-native process commands, secure broker binding and three independent backups."""
import ast
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.services.process import approved_process_service as aps
from client.commands.runtime.executor import CommandExecutor
from client.connection.message_router import ClientInboundMessageRouter
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


def row():
    return {'pid': 4199, 'name': 'python3', 'user': 'tester', 'exec_path': '/usr/bin/python3',
            'created_at': 42.0, 'cmdline': ['python3'], 'cwd': '/tmp', 'ppid': 2,
            'status': 'running', 'memory_rss': 500, 'threads': 1,
            'listening': [{'port': 9999, 'protocol': 'tcp', 'address': '127.0.0.1'}]}


def owner():
    messages = []
    host = SimpleNamespace(
        _interaction_grant={'token': 'grant'},
        _set_timeout=lambda *a, **k: None,
        _ensure_not_interrupted=lambda *a, **k: None,
        _send_interim_result=lambda *args: messages.append(args),
    )
    return host, messages


def test_shell_like_registry_and_positional_grammar():
    assert hasattr(CommandProcessMixin.kill_port, 'help')
    assert hasattr(CommandProcessMixin.kill_proc, 'help')
    assert hasattr(CommandProcessMixin.kill_process, 'help')
    assert not hasattr(BuiltinCommandHandler, 'kill_port')
    assert not hasattr(BuiltinCommandHandler, 'kill_proc')
    assert all(c['name'] not in ('kill_port', 'kill_proc')
               for c in BuiltinCommandHandler.WEB_COMMAND_TEMPLATES)
    assert aps.parse_target('9999', by_port=True) == {'port': 9999}
    assert aps.parse_target('9999 -9', by_port=True) == {'port': 9999, 'force': True}
    assert aps.parse_target('30565') == {'pid': 30565}
    assert aps.parse_target('python3 -9') == {'name': 'python3', 'force': True}
    with pytest.raises(aps.ProcessApprovalError):
        aps.parse_target('--pid 30565')
    with pytest.raises(aps.ProcessApprovalError):
        aps.parse_target('--port 9999', by_port=True)


def test_only_explicit_client_commands_are_issued_interaction_grants():
    grants = []
    class Grants:
        def issue_script_grant(self, **params):
            grants.append(params)
            return {'token': 'bound-token'}
    session = SimpleNamespace(context=SimpleNamespace(script_grant_service=Grants()))
    channel = ClientSessionCommandChannel(session)
    for command in ('pwd', 'kill_process 3', 'ls -la'):
        assert 'extra' not in channel.build_command_payload(command)
    for command in ('kill_port 9999', 'kill_proc 30565'):
        payload = channel.build_command_payload(command)
        assert payload['extra']['__script_grant__']['token'] == 'bound-token'
        assert grants[-1]['command_id'] == payload['id']
        assert grants[-1]['grant_request']['api_grants'] == ['interactions:request']


def test_active_client_command_grant_is_forwarded_and_not_reused(monkeypatch):
    runtime = object.__new__(CommandExecutor)
    runtime.context_store = SimpleNamespace(
        extract_timeout=lambda options: None,
        get_or_create=lambda command_id, timeout=None: None,
        clear=lambda command_id: None,
    )
    host = SimpleNamespace(bind_execution=lambda *a: None, _interaction_grant=None)
    runtime.get_commands = lambda: host
    req = runtime._build_request(17, options={'__script_grant__': {'token': 'active'}})
    result = runtime.execute_bound_request(req, lambda h: h._interaction_grant['token'])
    assert result == 'active'
    assert host._interaction_grant is None
    ordinary = runtime._build_request(18, options=None)
    assert ordinary.interaction_grant is None


def test_client_interaction_transport_uses_bound_grant(monkeypatch):
    calls = []
    class Api:
        def post_data(self, path, **opts):
            calls.append((path, opts))
            return {'status': 'rejected', 'value': False}
    monkeypatch.setattr('client.http.client_api.ClientApiClient', Api)
    ui = aps.ClientCommandInteractions(SimpleNamespace(
        _interaction_grant={'token': 'bound'}, _ensure_not_interrupted=lambda **k: None))
    assert not ui.approve('Proceed?', aps.build_preview(row(), port=9999))
    assert calls[0][1]['headers']['X-Script-Grant-Token'] == 'bound'
    assert calls[0][1]['json']['kind'] == 'preview'


def test_port_rejection_does_not_send_signal(monkeypatch):
    host, messages = owner()
    monkeypatch.setattr(aps, 'find_targets', lambda args: [row()])
    monkeypatch.setattr(aps.ClientCommandInteractions, 'approve', lambda *a, **k: None)
    monkeypatch.setattr(aps, 'terminate_verified', lambda *a, **k: pytest.fail('No signal before approval'))
    status, output = CommandProcessMixin._run_approved_process_command(host, '9999', by_port=True)
    assert status == 1 and 'rejected' in output
    assert any('Inspecting port 9999' in x[1] for x in messages)


def test_port_approved_verifies_target_before_signal(monkeypatch):
    host, messages = owner()
    called = []
    monkeypatch.setattr(aps, 'find_targets', lambda args: [row()])
    monkeypatch.setattr(aps.ClientCommandInteractions, 'approve', lambda *a, **k: {'force': True})
    monkeypatch.setattr(aps, 'terminate_verified', lambda r, **kw: (called.append((r, kw)), 'SIGKILL')[1])
    status, output = CommandProcessMixin._run_approved_process_command(host, '9999', by_port=True)
    assert status == 1 and 'SIGKILL' in output
    assert called[0][0]['pid'] == 4199 and called[0][1] == {'force': True, 'port': 9999}


def test_no_argument_requests_input_and_gives_error_not_silence(monkeypatch):
    host, messages = owner()
    monkeypatch.setattr(aps.ClientCommandInteractions, 'ask', lambda *a, **k: '9999')
    monkeypatch.setattr(aps, 'find_targets', lambda *a: [])
    status, output = CommandProcessMixin._run_approved_process_command(host, '', by_port=True)
    assert status == 0 and 'No matching process' in output
    assert any('9999' in text for _, text in messages)


def test_port_identity_cannot_change_after_approval(monkeypatch):
    class Proc:
        def create_time(self): return 42.0
        def name(self): return 'python3'
        def exe(self): return '/usr/bin/python3'
        def terminate(self): pytest.fail('Do not kill after port reassignment')
    import psutil
    monkeypatch.setattr(psutil, 'Process', lambda pid: Proc())
    monkeypatch.setattr(aps, '_port_owners', lambda port: set())
    with pytest.raises(aps.ProcessApprovalError, match='no longer owns'):
        aps.terminate_verified(row(), force=False, port=9999)


def test_three_backup_scripts_with_distinct_metadata():
    scripts = Path(__file__).resolve().parents[1] / 'server/resources/scripts/mac/recon'
    expected = ('personal_mac_backup', 'personal_mac_backup_preview_simple',
                'personal_mac_backup_preview')
    for name in expected:
        file = scripts / (name + '.py')
        assert file.is_file()
        tree = ast.parse(file.read_text())
        metadata = next(ast.literal_eval(node.value) for node in tree.body
                        if isinstance(node, ast.Assign) and any(
                            isinstance(t, ast.Name) and t.id == 'SCRIPT_METADATA'
                            for t in node.targets))
        assert metadata['name'] == 'mac/recon/' + name
    assert 'context.confirm(summary' in (scripts / 'personal_mac_backup_preview_simple.py').read_text()
    assert 'context.approve_preview(' in (scripts / 'personal_mac_backup_preview.py').read_text()


def test_local_listener_can_be_identified_without_stale_server_pyexec():
    child = subprocess.Popen([sys.executable, '-u', '-c',
        'import socket,time; s=socket.socket();s.bind(("127.0.0.1",0));s.listen();print(s.getsockname()[1],flush=True);time.sleep(12)'],
        stdout=subprocess.PIPE, text=True)
    try:
        port = int(child.stdout.readline().strip())
        assert child.pid in aps._port_owners(port)
        assert any(x['pid'] == child.pid for x in aps.find_targets({'port': port, 'force': False}))
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_actual_client_manifest_yields_only_plain_command_name_candidates():
    from client.commands.common.mixins.introspection_ops import CommandIntrospectionMixin
    from server.application.web.command_catalog_api import WebCommandCatalogApi

    class Commands(CommandProcessMixin, CommandIntrospectionMixin):
        pass

    manifest = Commands().get_command_manifest_payload()
    entries = [item for item in manifest if item['name'] in ('kill_port', 'kill_proc')]
    assert len(entries) == 2 and all('template' not in entry for entry in entries)
    client = SimpleNamespace(session_info=SimpleNamespace(command_manifest=manifest))
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _: client)
    catalog = WebCommandCatalogApi(
        server, SimpleNamespace(create=lambda _: SimpleNamespace(
            get_command_candidates=lambda: [dict(item) for item in BuiltinCommandHandler.WEB_COMMAND_TEMPLATES])))
    candidates = catalog.get_command_candidates('client-A')
    for name in ('kill_port', 'kill_proc'):
        rows = [c for c in candidates if c['name'] == name]
        assert len(rows) == 1 and rows[0]['template'] == name and rows[0]['source'] == 'client'
