"""Ordinary Client command grants come from trusted method metadata."""
from types import SimpleNamespace

from client.commands.common.commands import CommonCommands
from core.protocol.message_types import MSG_TYPE_SCRIPT
from core.utils.decorator import desc
from server.application.auth.script_grant_service import SCRIPT_GRANT_REQUEST_KEY
from server.connection.channel.session_command_channel import ClientSessionCommandChannel


INTERACTIVE_NAMES = ('kill_proc', 'kill_port')


def channel_and_requests():
    requests = []

    class GrantService:
        def issue_script_grant(self, **kwargs):
            requests.append(kwargs)
            return {'token': 'test-token'}

    session = SimpleNamespace(
        context=SimpleNamespace(script_grant_service=GrantService()),
    )
    return ClientSessionCommandChannel(session), requests


def test_interactive_process_commands_declare_scopes_at_method():
    for name in INTERACTIVE_NAMES:
        command = getattr(CommonCommands, name)
        assert command.api_grants == ('interactions:request',)
        assert command.help
    assert not getattr(CommonCommands.kill_process, 'api_grants')


def test_server_issues_declared_grants_for_commands_with_arguments():
    channel, requests = channel_and_requests()
    for name in INTERACTIVE_NAMES:
        result = channel.build_command_payload(f'{name} "some args"')
        assert result['extra']['__script_grant__']['token'] == 'test-token'
    assert [request['grant_request']['script_name'] for request in requests] == [
        f'client-command:{name}' for name in INTERACTIVE_NAMES
    ]
    assert all(request['grant_request']['api_grants'] == ['interactions:request'] for request in requests)


def test_server_does_not_grant_unknown_or_non_interactive_commands():
    channel, requests = channel_and_requests()
    for command in ('kill_process 12', 'help', 'kill_by_port 33',
                    'interaction_demo_bogus', 'cat test', '"broken'):
        assert 'extra' not in channel.build_command_payload(command)
    assert requests == []


def test_server_only_uses_trusted_registry_not_client_manifest():
    channel, requests = channel_and_requests()
    channel.session.session_info = SimpleNamespace(command_manifest=[
        {'name': 'help', 'api_grants': ['interactions:request']},
    ])
    assert 'extra' not in channel.build_command_payload('help')
    assert requests == []


def test_new_decorated_common_command_needs_no_server_name_edit(monkeypatch):
    @desc('Test extra command', api_grants=('interactions:request',))
    def added_command(self, arg=''):
        return 1, 'ok'

    monkeypatch.setattr(CommonCommands, 'annotation_test_command', added_command, raising=False)
    channel, requests = channel_and_requests()
    assert channel.build_command_payload('annotation_test_command')['extra']['__script_grant__']['token'] == 'test-token'
    assert requests[0]['grant_request']['script_name'] == 'client-command:annotation_test_command'


def test_script_payload_uses_existing_explicit_grant_path():
    channel, requests = channel_and_requests()
    grant_request = {'script_name': 'test/script', 'api_grants': ['interactions:request']}
    result = channel.build_command_payload('test/script', MSG_TYPE_SCRIPT,
                                           extra={SCRIPT_GRANT_REQUEST_KEY: grant_request})
    assert result['extra']['__script_grant__']['token'] == 'test-token'
    assert requests[0]['grant_request'] == grant_request
