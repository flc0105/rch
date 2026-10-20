"""Client regular-command Interaction Broker integration and registry tests."""
from types import SimpleNamespace

import pytest

from client.commands.common.services.interaction_service import CommandInteractions, CommandInteractionError
from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.groups import CommonRuntimeCommands
from client.commands.runtime.shell_command_runner import ShellCommandRunner
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


def owner(token='active-grant'):
    return SimpleNamespace(_interaction_grant={'token': token} if token else None,
                           _checkpoint=lambda **kw: None,
                           _set_timeout=lambda _: None,
                           _send_interim_result=lambda *args: None)


def test_client_commands_are_registered_without_old_aliases():
    names = ('kill_port', 'kill_proc')
    for name in names:
        assert hasattr(CommonRuntimeCommands, name)
        assert hasattr(getattr(CommonRuntimeCommands, name), 'help')
        assert name not in [x['name'] for x in BuiltinCommandHandler.REGISTRY.candidates()]
    for old in ('kill_by_port', 'kill_process_preview'):
        assert not hasattr(CommandProcessMixin, old)
    for name in ('kill_process', 'kill_connection', 'disconnect'):
        assert not hasattr(BuiltinCommandHandler, name)
    assert BuiltinCommandHandler.REGISTRY.get('disconnect') is None
    for name in ('interaction_demo', 'interaction_advanced_demo', 'interaction_preview_demo'):
        assert not hasattr(CommonRuntimeCommands, name)
    assert not hasattr(CommonRuntimeCommands, 'disconnect')


def test_plain_command_resolution_uses_normal_client_registry():
    runner = ShellCommandRunner(SimpleNamespace())
    for name in ('kill_port', 'kill_proc'):
        cmd = runner._resolve_builtin_command(CommonRuntimeCommands, name)
        assert cmd is not None and hasattr(cmd, 'help')
    assert runner._resolve_builtin_command(CommonRuntimeCommands, 'kill_by_port') is None


def test_command_interactions_uses_bound_grant(monkeypatch):
    from client.http import client_api
    recorded = []
    class API:
        def post_data(self, path, **kw):
            recorded.append((path, kw))
            return {'status': 'answered', 'value': True}
    monkeypatch.setattr(client_api, 'ClientApiClient', API)
    assert CommandInteractions(owner()).confirm('Proceed?', title='Confirm')
    assert recorded[0][0] == '/api/interactions/client/request'
    assert recorded[0][1]['headers'] == {'X-Script-Grant-Token': 'active-grant'}
    assert recorded[0][1]['json']['kind'] == 'confirm'
    with pytest.raises(CommandInteractionError, match='grant'):
        CommandInteractions(owner(token='')).confirm('Proceed?')


def test_secret_input_and_preview_rejection(monkeypatch):
    from client.http import client_api
    requests = []
    class API:
        def post_data(self, path, **kw):
            requests.append(kw['json'])
            if kw['json']['kind'] == 'secret':
                return {'status': 'answered', 'value': 'secret text'}
            return {'status': 'rejected', 'value': False}
    monkeypatch.setattr(client_api, 'ClientApiClient', API)
    ui = CommandInteractions(owner())
    assert ui.ask('Secret?', title='Secret', secret=True) == 'secret text'
    assert not ui.approve_preview('Review', {'rows': []})
    assert [x['kind'] for x in requests] == ['secret', 'preview']
    assert requests[0]['message'] == 'Secret?'


def test_each_interactive_command_receives_scoped_grant():
    issued = []
    class GrantService:
        def issue_script_grant(self, **kw):
            issued.append(kw)
            return {'token': 't'}
    session = SimpleNamespace(context=SimpleNamespace(script_grant_service=GrantService()))
    channel = ClientSessionCommandChannel(session)
    for name in ('kill_port', 'kill_proc'):
        result = channel.build_command_payload(name)
        assert result['extra']['__script_grant__']['token'] == 't'
    for old in ('kill_by_port', 'kill_process_preview'):
        assert 'extra' not in channel.build_command_payload(old)
    assert len(issued) == 2
