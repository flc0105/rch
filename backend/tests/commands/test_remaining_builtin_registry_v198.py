"""The four simple builtins use one declared invocation and Result projection."""
import json
from types import SimpleNamespace

import pytest

from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.completion.command_completion_providers import (
    RegisteredServerSubcommandCompletionProvider, HelpCommandCompletionProvider,
)
from core.command_completion.models import CompletionContext
from core.protocol.result_envelope import ResultEnvelope
from core.utils.command_output import render_result_payload


@pytest.mark.parametrize('command,text,action,arguments', [
    ('help', '', 'help', {'target': None, 'subcommand': None}),
    ('help', 'job start', 'help', {'target': 'job', 'subcommand': 'start'}),
    ('help', 'client', 'help', {'target': 'client'}),
    ('httpctl', '', 'help', {'json': False}),
    ('httpctl', '-h', 'help', {'json': False}),
    ('httpctl', '--help', 'help', {'json': False}),
    ('httpctl', 'resume --client-id offline-123 --json', 'resume',
     {'client-id': 'offline-123', 'json': True}),
    ('httpctl', 'kill --json', 'kill', {'json': True}),
    ('gopin', 'saved work dir', 'go', {'command': 'saved work dir'}),
    ('upload', '/tmp/a name.txt', 'upload', {'command': '/tmp/a name.txt'}),
])
def test_declared_builtin_invocation(command, text, action, arguments):
    inv = SERVER_COMMAND_REGISTRY.parse_invocation(command, text)
    assert inv.action == action
    for key, value in arguments.items():
        assert inv.arguments[key] == value


@pytest.mark.parametrize('command,text', [
    ('help', 'job start extra'),
    ('httpctl', 'resume --client-id one --client-id two'),
    ('httpctl', 'kill --client-id foo'),
    ('httpctl', 'kill extra'),
    ('httpctl', 'resume --missing foo'),
])
def test_invalid_arguments_rejected_by_registry(command, text):
    with pytest.raises(ValueError):
        SERVER_COMMAND_REGISTRY.parse_invocation(command, text)


def test_raw_tail_preserves_inner_json_flags_and_whitespace():
    for root, tail in [('upload', '/tmp/a  b --json.txt'),
                       ('gopin', 'saved  --json path')]:
        inv = SERVER_COMMAND_REGISTRY.parse_invocation(root, tail)
        assert inv.arguments['command'] == tail
        assert inv.output_format == 'text'


def test_registry_derived_completion_for_help_and_httpctl():
    help_items = HelpCommandCompletionProvider().complete(CompletionContext(command_name='help'))
    targets = [item.insert_text for item in help_items]
    assert 'help job start' in targets
    assert 'help config set' in targets
    commands = RegisteredServerSubcommandCompletionProvider().complete(
        CompletionContext(command_name='httpctl'))
    assert {item.name for item in commands} == {'kill', 'relaunch', 'clone', 'resume', 'help'}


def test_httpctl_queue_only_and_result_json(monkeypatch):
    from server.application.command.control_builtin_support import ControlBuiltinSupport
    support = ControlBuiltinSupport.__new__(ControlBuiltinSupport)
    support.conn = SimpleNamespace(session_info=SimpleNamespace(client_id='online-1'))
    captured = []
    support.control_command_store = SimpleNamespace(
        set_pending_command=lambda ident, action: captured.append((ident, action)) or {'client_id': ident})
    reply = list(support.httpctl(SERVER_COMMAND_REGISTRY.parse_invocation(
        'httpctl', 'resume --client-id offline-1 --json')))
    assert captured == [('offline-1', 'resume')]
    assert reply[0][0] == 1
    assert set(json.loads(reply[0][1])) == {'status', 'message'}
    assert list(support.httpctl(SERVER_COMMAND_REGISTRY.parse_invocation('httpctl', 'help')))[0][0] == 1


def test_gopin_list_and_jump_results(monkeypatch):
    from server.application.command.builtin_command_support import PinnedPathBuiltinSupport
    support = PinnedPathBuiltinSupport.__new__(PinnedPathBuiltinSupport)
    support.list_pinned_paths = lambda: [{'display_name': 'work', 'path': '/tmp/work'}]
    support._get_machine_id = lambda: 'machine-1'
    support.pinned_path_store = SimpleNamespace(get_item_by_name=lambda _machine, _name:
        {'path': '/tmp/work'})
    support.command_processor_factory = lambda: lambda text: lambda: iter([(1, 'cwd=/tmp/work')])
    listing = list(support.gopin(SERVER_COMMAND_REGISTRY.parse_invocation('gopin', '')))
    assert listing[0][0] == 1 and 'work' in listing[0][1]
    jump = list(support.gopin(SERVER_COMMAND_REGISTRY.parse_invocation('gopin', 'work')))
    assert 'gopin work' in jump[0][1] and jump[1] == (1, 'cwd=/tmp/work')


def test_result_envelope_message_json_contract():
    assert json.loads(render_result_payload(ResultEnvelope(message='queued').as_payload(), 'json')) == {
        'status': 'success', 'message': 'queued'}
