"""Declarative confirmation without modifying command implementations."""
from types import SimpleNamespace

import pytest

from client.commands.common.commands import CommonCommands
from client.commands.common.services.interaction_service import CommandInteractions
from client.commands.platform.mac import MacCommands
from client.commands.runtime.shell_command_runner import ShellCommandRunner
from core.utils.decorator import confirm, desc
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


def command_host(token='active-token'):
    return SimpleNamespace(
        _interaction_grant={'token': token} if token else None,
        _checkpoint=lambda **kw: None,
        calls=[],
    )


def grant_channel(os_alias=''):
    issued = []

    class Grants:
        def issue_script_grant(self, **kw):
            issued.append(kw)
            return {'token': 'active-token'}

    session = SimpleNamespace(
        session_info=SimpleNamespace(os_alias=os_alias),
        context=SimpleNamespace(script_grant_service=Grants()),
    )
    return ClientSessionCommandChannel(session), issued


@pytest.mark.parametrize('order', ['desc_outer', 'confirm_outer'])
def test_order_independent_confirm_and_desc(monkeypatch, order):
    def action(self, arg=''):
        self.calls.append(arg)
        return 1, 'Executed'

    if order == 'desc_outer':
        wrapped = desc('Sensitive operation', api_grants=('scripts:read',))(confirm(action))
    else:
        wrapped = confirm(desc('Sensitive operation', api_grants=('scripts:read',))(action))

    assert wrapped.help == 'Sensitive operation'
    assert wrapped.requires_confirmation is True
    assert set(wrapped.api_grants) == {'scripts:read', 'interactions:request'}
    assert wrapped.__name__ == 'action'
    host = command_host()
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: True)
    assert wrapped(host, '--dry-run') == (1, 'Executed')
    assert host.calls == ['--dry-run']


@pytest.mark.parametrize('answer', [False, True])
def test_confirm_gates_execution(monkeypatch, answer):
    prompts = []

    @confirm('Delete the selected files?')
    @desc('Sensitive command')
    def action(self, arg=''):
        self.calls.append(arg)
        return 1, 'done'

    def reply(self, message, *, title):
        prompts.append((message, title))
        return answer

    monkeypatch.setattr(CommandInteractions, 'confirm', reply)
    host = command_host()
    result = action(host, 'test')
    if answer:
        assert result == (1, 'done')
        assert host.calls == ['test']
    else:
        assert result[0] == 0
        assert not host.calls
    assert prompts == [('Delete the selected files?', 'Confirm command execution')]


def test_existing_broker_transport_is_used_before_method(monkeypatch):
    from client.http import client_api

    calls = []

    class Api:
        def post_data(self, path, **kwargs):
            calls.append((path, kwargs))
            return {'status': 'answered', 'value': True}

    monkeypatch.setattr(client_api, 'ClientApiClient', Api)

    @desc('Broker-backed guarded command')
    @confirm
    def action(self, arg=''):
        self.calls.append(arg)
        return 1, 'done'

    host = command_host()
    assert action(host, 'test') == (1, 'done')
    assert calls[0][0] == '/api/interactions/client/request'
    assert calls[0][1]['headers']['X-Script-Grant-Token'] == 'active-token'
    assert calls[0][1]['json']['kind'] == 'confirm'
    assert host.calls == ['test']


def test_no_grant_or_broker_failure_does_not_execute(monkeypatch):
    @desc('No-execution test')
    @confirm
    def action(self):
        self.calls.append(True)
        return 1, 'wrong'

    host = command_host(token='')
    result = action(host)
    assert result[0] == 0 and 'grant' in result[1]
    assert not host.calls

    def network_failure(*a, **kw):
        raise OSError('Broker unavailable')

    monkeypatch.setattr(CommandInteractions, 'confirm', network_failure)
    result = action(command_host())
    assert result[0] == 0 and 'Broker unavailable' in result[1]


def test_server_grants_only_trusted_common_confirm_annotation(monkeypatch):
    @desc('A safely registered command')
    @confirm
    def sample(self, arg=''):
        return 1, arg

    monkeypatch.setattr(CommonCommands, 'sample_confirm', sample, raising=False)
    channel, issued = grant_channel()
    payload = channel.build_command_payload('sample_confirm payload')
    assert payload['extra']['__script_grant__']['token'] == 'active-token'
    assert issued[0]['grant_request']['api_grants'] == ['interactions:request']

    channel.session.session_info.command_manifest = [
        {'name': 'help', 'api_grants': ['interactions:request']},
    ]
    assert 'extra' not in channel.build_command_payload('help')
    assert 'extra' not in channel.build_command_payload('not_a_command')


def test_server_grants_platform_only_confirm_annotation(monkeypatch):
    @confirm
    @desc('Mac-only sample command')
    def example(self):
        return 1, 'ok'

    monkeypatch.setattr(MacCommands, 'mac_sample_confirm', example, raising=False)
    mac_channel, issued = grant_channel('mac')
    assert mac_channel.build_command_payload('mac_sample_confirm')['extra']['__script_grant__']
    assert issued[0]['grant_request']['api_grants'] == ['interactions:request']

    win_channel, win_issued = grant_channel('win')
    assert 'extra' not in win_channel.build_command_payload('mac_sample_confirm')
    assert win_issued == []


def test_actual_command_runner_dispatches_guarded_method(monkeypatch):
    @confirm
    @desc('Guarded command')
    def sample(self, arg=''):
        self.calls.append(arg)
        return 1, 'done'

    host = command_host()
    host.sample = sample.__get__(host)
    executor = SimpleNamespace(
        command_variable_resolver=SimpleNamespace(resolve=lambda value, **kw: value),
        execute_bound_request=lambda request, invoke: invoke(host),
    )
    request = SimpleNamespace(command_id=12)
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda *a, **kw: False)
    result = ShellCommandRunner(executor).execute(request, 'sample hidden')
    assert result[0] == 0
    assert host.calls == []


def test_plain_decorated_commands_are_unchanged():
    assert getattr(CommonCommands.kill_process, 'api_grants', ()) == ()
    assert not getattr(CommonCommands.kill_process, 'requires_confirmation', False)


def test_invalid_message_rejected_at_definition_time():
    with pytest.raises(ValueError, match='nonempty'):
        confirm('   ')(lambda self: None)
