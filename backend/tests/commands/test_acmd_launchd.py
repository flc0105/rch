"""macOS launchd ACMD uses the existing SDK and the common argument registry."""

from types import SimpleNamespace
import json

import pytest

from client.commands.arguments.registry import ArgumentCommandRegistry
from client.commands.platform.mac import MacCommands
from client.commands.platform.linux import LinuxCommands
from client.runtime.sdk import launchd
from client.commands.common.services.interaction_service import CommandInteractions, CommandInteractionError
from server.connection.channel.session_command_channel import ClientSessionCommandChannel
from core.protocol.message_types import MSG_TYPE_ACMD
from server.application.command.command_planner import CommandPlanner


def _registry():
    return ArgumentCommandRegistry(MacCommands(socket=SimpleNamespace()))


def _execute(registry, command):
    payload = CommandPlanner.__new__(CommandPlanner).parse_argument_command(command)
    return registry.execute(payload)


def test_launchd_is_registered_only_on_macos():
    mac = _registry()
    assert mac.has_command('launchd')
    assert not ArgumentCommandRegistry(LinuxCommands(socket=SimpleNamespace())).has_command('launchd')
    assert 'launchd' in _execute(mac, 'acmd help')[1]
    status, help_text = _execute(mac, 'acmd help launchd')
    assert status == 1
    assert 'acmd launchd <action> <kind>' in help_text
    assert '--keep_alive' in help_text
    assert '--json' in help_text


@pytest.mark.parametrize('command,expected', [
    ('acmd launchd install agent --scope user --keep-alive true',
     {'action': 'install', 'kind': 'agent', 'scope': 'user', 'keep_alive': True}),
    ('acmd launchd --action start --kind agent',
     {'action': 'start', 'kind': 'agent'}),
    ('acmd launchd status daemon',
     {'action': 'status', 'kind': 'daemon'}),
    ('acmd launchd --action install --kind agent --keep_alive=false --run_at_load=false',
     {'action': 'install', 'kind': 'agent', 'keep_alive': False, 'run_at_load': False}),
    ('acmd launchd --action install --kind agent --keep-alive false --run-at-load false',
     {'action': 'install', 'kind': 'agent', 'keep_alive': False, 'run_at_load': False}),
    ('acmd launchd uninstall agent --label com.example.service --target-user alice --scope global',
     {'action': 'uninstall', 'kind': 'agent', 'label': 'com.example.service',
      'target_user': 'alice', 'scope': 'global'}),
])
def test_launchd_commands_dispatch_to_sdk(monkeypatch, command, expected):
    called = []

    def fake_manage(**kwargs):
        called.append(kwargs)
        return {
            'ok': True,
            'action': kwargs['action'],
            'kind': kwargs['kind'],
            'label': kwargs['label'],
            'installed': True,
            'loaded': False,
            'running': False,
        }

    monkeypatch.setattr(launchd, 'manage', fake_manage)
    monkeypatch.setattr(CommandInteractions, 'approve_preview', lambda *a, **kw: True)
    status, output = _execute(_registry(), command)
    assert status == 1
    assert 'Action: ' in output
    assert len(called) == 1
    for key, value in expected.items():
        assert called[0][key] == value
    assert called[0]['label'] == expected.get('label', 'com.rch.client')
    assert called[0]['run_at_load'] == expected.get('run_at_load', True)
    assert called[0]['target_user'] == expected.get('target_user', None)


def test_launchd_daemon_ignores_agent_specific_parameters(monkeypatch):
    called = []
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: called.append(kwargs) or {'ok': True})
    monkeypatch.setattr(CommandInteractions, 'approve_preview', lambda *a, **kw: True)
    assert _execute(_registry(), 'acmd launchd install daemon --scope global --target-user alice')[0] == 1
    assert called[0]['scope'] == 'user'
    assert called[0]['target_user'] is None


def test_launchd_json_returns_structured_sdk_result(monkeypatch):
    result = {
        'ok': True,
        'action': 'status',
        'kind': 'agent',
        'scope': 'user',
        'label': 'com.example.agent',
        'target_user': 'alice',
        'target_uid': 501,
        'plist_path': '/Users/alice/Library/LaunchAgents/com.example.agent.plist',
        'domain': 'gui/501',
        'service_target': 'gui/501/com.example.agent',
        'installed': True,
        'loaded': True,
        'running': True,
        'pid': 1234,
        'state': 'running',
    }
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: result)
    monkeypatch.setattr(CommandInteractions, 'approve_preview', lambda *a, **kw: True)
    monkeypatch.setattr(launchd, 'format_result', lambda *_: (_ for _ in ()).throw(AssertionError('JSON path must use structured rendering')))

    status, output = _execute(_registry(), 'acmd launchd status agent --json')

    assert status == 1
    payload = json.loads(output)
    assert payload == result
    assert payload['installed'] is True
    assert payload['pid'] == 1234


def test_launchd_json_keeps_no_confirm_bypass(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Interaction Broker must not be invoked')

    monkeypatch.setattr(CommandInteractions, '__init__', forbidden)
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: {
        'ok': True, 'action': 'status', 'kind': 'agent', 'installed': False,
        'loaded': False, 'running': False, 'pid': None,
    })
    status, output = _execute(_registry(), 'acmd launchd status agent --json --no-confirm')
    assert status == 1
    assert json.loads(output)['action'] == 'status'


@pytest.mark.parametrize('command,fragment', [
    ('acmd launchd foo agent', 'Invalid launchd action'),
    ('acmd launchd install foo', 'Invalid launchd kind'),
    ('acmd launchd install agent --keep-alive maybe', 'must be true/false'),
    ('acmd launchd install agent --unknown value', 'Unknown option'),
    ('acmd launchd install agent --keep-alive false --keep_alive true', 'Duplicate option'),
])
def test_launchd_rejects_invalid_inputs_without_touching_sdk(monkeypatch, command, fragment):
    calls = []
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: calls.append(kwargs))
    status, message = _execute(_registry(), command)
    assert status == 0
    assert fragment in message
    assert not calls


def test_launchd_sdk_failure_returns_error(monkeypatch):
    def fail(**_kwargs):
        raise RuntimeError('root privileges required')

    monkeypatch.setattr(launchd, 'manage', fail)
    monkeypatch.setattr(CommandInteractions, 'approve_preview', lambda *a, **kw: True)
    status, message = _execute(_registry(), 'acmd launchd install daemon')
    assert status == 0
    assert 'root privileges required' in message


def test_launchd_help_does_not_touch_sdk(monkeypatch):
    calls = []
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: calls.append(kwargs))
    status, message = _execute(_registry(), 'acmd launchd --help')
    assert status == 1
    assert 'acmd launchd' in message
    assert not calls


def _interactions(monkeypatch, *, approved=True, selections=None):
    selected = []
    previews = []
    choices = iter(selections or ())

    def select(_self, message, labels, *, title):
        value = next(choices)
        assert value in labels
        selected.append((title, value))
        return value

    def approve(_self, message, preview, *, title):
        assert title == 'Review launchd operation'
        previews.append(preview)
        return approved

    monkeypatch.setattr(CommandInteractions, 'select', select)
    monkeypatch.setattr(CommandInteractions, 'approve_preview', approve)
    return selected, previews


def test_launchd_full_arguments_uses_only_preview_and_effective_install_values(monkeypatch):
    selected, previews = _interactions(monkeypatch)
    called = []
    monkeypatch.setattr(launchd, 'manage', lambda **args: called.append(args) or {'ok': True})
    assert _execute(_registry(), 'acmd launchd install agent --scope global --target-user alice '
                       '--label com.example.agent --keep-alive false --run-at-load false')[0] == 1
    assert selected == []
    assert len(previews) == 1
    values = {row['label']: row['value'] for row in previews[0]['summary']}
    assert values == {'Action': 'install', 'Type': 'LaunchAgent', 'Label': 'com.example.agent',
                      'KeepAlive': 'false', 'RunAtLoad': 'false', 'Scope': 'global', 'Target user': 'alice'}
    assert called[0]['keep_alive'] is False and called[0]['run_at_load'] is False


@pytest.mark.parametrize('command,selections,expected_titles', [
    ('acmd launchd', ['install', 'agent'], ['Launchd action', 'Launchd type']),
    ('acmd launchd install', ['daemon'], ['Launchd type']),
    ('acmd launchd --kind agent', ['status'], ['Launchd action']),
    ('acmd launchd --action start', ['agent'], ['Launchd type']),
])
def test_launchd_missing_choices_prompt_then_preview(monkeypatch, command, selections, expected_titles):
    selected, previews = _interactions(monkeypatch, selections=selections)
    called = []
    monkeypatch.setattr(launchd, 'manage', lambda **args: called.append(args) or {'ok': True})
    status, _ = _execute(_registry(), command)
    assert status == 1
    assert [name for name, _ in selected] == expected_titles
    assert len(previews) == 1
    assert len(called) == 1
    assert called[0]['label'] == 'com.rch.client'
    assert called[0]['keep_alive'] is True
    assert called[0]['run_at_load'] is True
    summary = {row['label']: row['value'] for row in previews[0]['summary']}
    assert summary['KeepAlive'] == 'true'
    assert summary['RunAtLoad'] == 'true'
    if called[0]['kind'] == 'agent':
        assert summary['Scope'] == 'user'
        assert summary['Target user'] == 'Current GUI user (automatic)'
    else:
        assert 'Scope' not in summary
        assert called[0]['scope'] == 'user'
        assert called[0]['target_user'] is None


@pytest.mark.parametrize('command', [
    'acmd launchd status agent',
    'acmd launchd uninstall daemon',
    'acmd launchd',
])
def test_launchd_rejection_never_executes_sdk(monkeypatch, command):
    _interactions(monkeypatch, approved=False, selections=['status', 'agent'])
    called = []
    monkeypatch.setattr(launchd, 'manage', lambda **args: called.append(args) or {'ok': True})
    status, message = _execute(_registry(), command)
    assert status == 0
    assert 'not approved' in message
    assert called == []


def test_launchd_cancelled_selection_never_executes_sdk(monkeypatch):
    def cancel(*args, **kwargs):
        raise CommandInteractionError('Input rejected, expired, or cancelled')
    monkeypatch.setattr(CommandInteractions, 'select', cancel)
    calls = []
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: calls.append(kwargs))
    status, message = _execute(_registry(), 'acmd launchd')
    assert status == 0 and 'cancelled' in message
    assert calls == []


def test_launchd_without_broker_grant_fails_closed(monkeypatch):
    called = []
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: called.append(kwargs))
    # A bare registry test has no bound Web Task and consequently no Broker grant.
    status, message = _execute(_registry(), 'acmd launchd status agent')
    assert status == 0
    assert 'no active interaction grant' in message
    assert called == []


def test_launchd_server_grant_is_signed_from_trusted_mac_registration():
    issued = []

    class StubGrants:
        def issue_script_grant(self, *, session, command_id, grant_request):
            issued.append((command_id, grant_request))
            return {'token': 'sample', 'scopes': grant_request['api_grants']}

    session = SimpleNamespace(
        session_info=SimpleNamespace(os_alias='mac'),
        context=SimpleNamespace(script_grant_service=StubGrants()),
    )
    channel = ClientSessionCommandChannel(session)
    extra = {'name': 'launchd', 'args': {'_args': ['status', 'agent']}}
    sent = channel.build_command_payload('acmd launchd status agent', MSG_TYPE_ACMD, extra)
    assert sent['extra']['__script_grant__']['scopes'] == ['interactions:request']
    assert issued[0][1]['script_name'] == 'client-acmd:launchd'
    assert '__script_grant_request__' not in sent['extra']
    # The grant cannot be tricked into appearing for the same name on Linux.
    linux_session = SimpleNamespace(
        session_info=SimpleNamespace(os_alias='linux'),
        context=SimpleNamespace(script_grant_service=StubGrants()),
    )
    no_grant = ClientSessionCommandChannel(linux_session).build_command_payload(
        'acmd launchd status agent', MSG_TYPE_ACMD, extra)
    assert '__script_grant__' not in no_grant['extra']
    assert len(issued) == 1


def test_launchd_invalid_args_do_not_request_approval(monkeypatch):
    def unexpected(*a, **k):
        raise AssertionError('must not request an interaction with invalid args')
    monkeypatch.setattr(CommandInteractions, 'approve_preview', unexpected)
    status, message = _execute(_registry(), 'acmd launchd install agent --keep-alive nope')
    assert status == 0
    assert 'must be true/false' in message


@pytest.mark.parametrize('command', [
    'acmd launchd status agent --no-confirm',
    'acmd launchd install daemon --keep-alive false --run-at-load false --no-confirm',
    'acmd launchd --action start --kind agent --no-confirm',
])
def test_launchd_no_confirm_bypasses_every_interaction(monkeypatch, command):
    called = []
    def forbidden(*args, **kwargs):
        raise AssertionError('Interaction Broker must not be invoked for --no-confirm')
    monkeypatch.setattr(CommandInteractions, '__init__', forbidden)
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: called.append(kwargs) or {'ok': True})
    status, message = _execute(_registry(), command)
    assert status == 1, message
    assert len(called) == 1


@pytest.mark.parametrize('command', [
    'acmd launchd --no-confirm',
    'acmd launchd install --no-confirm',
    'acmd launchd --kind agent --no-confirm',
])
def test_launchd_no_confirm_requires_both_choices_and_never_asks(monkeypatch, command):
    calls = []
    monkeypatch.setattr(launchd, 'manage', lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(CommandInteractions, '__init__', lambda *a, **k: (_ for _ in ()).throw(AssertionError('No Broker')))
    status, output = _execute(_registry(), command)
    assert status == 0
    assert '--no-confirm requires both action and kind' in output
    assert not calls


def test_launchd_server_skips_grant_for_no_confirm():
    issued = []
    class GrantService:
        def issue_script_grant(self, **kwargs):
            issued.append(kwargs)
            return {'token': 'unexpected'}
    session = SimpleNamespace(
        session_info=SimpleNamespace(os_alias='mac'),
        context=SimpleNamespace(script_grant_service=GrantService()),
    )
    channel = ClientSessionCommandChannel(session)
    extra = {'name': 'launchd', 'args': {'_args': ['status', 'agent'], 'no-confirm': True}}
    sent = channel.build_command_payload('acmd launchd status agent --no-confirm', MSG_TYPE_ACMD, extra)
    assert not issued
    assert '__script_grant__' not in sent['extra']
