"""Registered session commands must be authorized automatically before confirmation."""
from types import SimpleNamespace

import pytest

from client.commands.common.commands import CommonCommands
from client.commands.common.mixins import session_ops
from client.commands.common.services.interaction_service import CommandInteractions
from client.commands.runtime.executor import CommandExecutor
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


class GrantService:
    def __init__(self):
        self.requests = []

    def issue_script_grant(self, **kwargs):
        self.requests.append(kwargs)
        return {'token': 'issued-token'}


def make_channel():
    service = GrantService()
    session = SimpleNamespace(
        context=SimpleNamespace(script_grant_service=service),
        session_info=SimpleNamespace(os_alias='mac'),
    )
    return ClientSessionCommandChannel(session), service


@pytest.mark.parametrize('name', ('kill_instance', 'relaunch_instance'))
def test_decorated_commands_auto_receive_interaction_grant(name):
    method = getattr(CommonCommands, name)
    assert method.requires_confirmation is True
    assert method.api_grants == ('interactions:request',)
    assert method.__wrapped__  # The existing method implementation remains wrapped, not rewritten.

    channel, grant_service = make_channel()
    payload = channel.build_command_payload(name)
    assert payload['extra']['__script_grant__']['token'] == 'issued-token'
    assert grant_service.requests[0]['grant_request']['script_name'] == f'client-command:{name}'
    assert grant_service.requests[0]['grant_request']['api_grants'] == ['interactions:request']


def test_grant_is_bound_by_client_executor_and_used_by_confirmation(monkeypatch):
    from client.http import client_api
    channel, _ = make_channel()
    payload = channel.build_command_payload('relaunch_instance')
    executor = CommandExecutor.__new__(CommandExecutor)
    calls = []
    executor.context_store = SimpleNamespace(extract_timeout=lambda *_: None)
    executor._get_or_create_execution_context = lambda command_id, timeout=None: object()
    owner = SimpleNamespace(
        bind_execution=lambda command_id, context: None,
        socket=object(),
        _checkpoint=lambda **kw: None,
    )
    request = executor._build_request(payload['id'], options=payload['extra'])
    executor._bind_execution(owner, request)
    assert owner._interaction_grant['token'] == 'issued-token'

    class FakeApi:
        def post_data(self, path, **kwargs):
            calls.append((path, kwargs))
            return {'status': 'answered', 'value': True}

    monkeypatch.setattr(client_api, 'ClientApiClient', FakeApi)
    monkeypatch.setattr(session_ops, 'reset', lambda socket: calls.append(('reset', socket)))
    CommonCommands.relaunch_instance(owner)
    assert calls[0][0] == '/api/interactions/client/request'
    assert calls[0][1]['headers']['X-Script-Grant-Token'] == 'issued-token'
    assert calls[0][1]['json']['message'] == 'Restart this Client process and reconnect to the Server?'
    assert calls[1] == ('reset', owner.socket)


@pytest.mark.parametrize('name', ('kill_instance', 'relaunch_instance'))
def test_refusal_does_not_enter_session_command_body(monkeypatch, name):
    executed = []
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: False)
    monkeypatch.setattr(session_ops, 'reset', lambda *_: executed.append('reset'))
    monkeypatch.setattr(session_ops.sys, 'exit', lambda *args: executed.append('exit'))
    sock = SimpleNamespace(close=lambda: executed.append('close'))
    owner = SimpleNamespace(socket=sock, _interaction_grant={'token': 'token'})
    result = getattr(CommonCommands, name)(owner)
    assert result[0] == 0
    assert executed == []


def test_plain_command_does_not_receive_grant():
    channel, _ = make_channel()
    assert 'extra' not in channel.build_command_payload('help')


@pytest.mark.parametrize('name,expected', [
    ('kill_instance', 'Terminate this Client session and close its connection?'),
    ('relaunch_instance', 'Restart this Client process and reconnect to the Server?'),
])
def test_session_prompts_are_specific_and_execute_only_on_approval(monkeypatch, name, expected):
    prompted = []
    executed = []
    monkeypatch.setattr(CommandInteractions, 'confirm',
                        lambda self, text, **kw: (prompted.append(text), True)[1])
    monkeypatch.setattr(session_ops, 'reset', lambda sock: executed.append('restart'))
    monkeypatch.setattr(session_ops.sys, 'exit', lambda *_: executed.append('exit'))
    owner = SimpleNamespace(socket=SimpleNamespace(close=lambda: executed.append('close')))
    getattr(CommonCommands, name)(owner)
    assert prompted == [expected]
    assert executed == (['close', 'exit'] if name == 'kill_instance' else ['restart'])
