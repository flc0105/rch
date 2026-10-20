"""Help presentation and builtin-command removal regressions."""
from types import SimpleNamespace

from client.commands.common.commands import CommonCommands
from client.commands.common.mixins.introspection_ops import CommandIntrospectionMixin
from core.utils.command_help import render_grouped_client_help
from server.application.command.builtin_command_handler import BuiltinCommandHandler
from server.application.command.builtin_command_support import PinnedPathBuiltinSupport
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


def test_original_client_help_group_order_is_restored():
    grouped = {
        'system': [('pwd', 'Print working directory')],
        'session': [('help', 'Show available commands')],
        'file': [('download', 'Download a file')],
        'shell': [('shell', 'Run shell command')],
    }
    text = render_grouped_client_help(grouped)
    assert text.splitlines() == [
        '[Shell / Execution]', 'shell                   Run shell command', '',
        '[File]', 'download                Download a file', '',
        '[Session]', 'help                    Show available commands', '',
        '[system]', 'pwd                     Print working directory',
    ]


def test_server_help_reuses_client_groups_and_never_lists_alias_values():
    handler = BuiltinCommandHandler.__new__(BuiltinCommandHandler)
    handler.conn = SimpleNamespace(session_info=SimpleNamespace(command_manifest=[
        {'name': 'pwd', 'group': 'system', 'help': 'Print working directory', 'suggest': True},
        {'name': 'download', 'group': 'file', 'help': 'Download a file', 'suggest': True},
        {'name': 'private_rpc', 'group': 'process', 'help': 'Hidden', 'suggest': False},
        {'name': 'acmd', 'group': 'acmd', 'help': 'Autocomplete placeholder'},
        {'name': 'acmd example', 'group': 'acmd', 'help': 'Example command'},
        {'name': 'acmd help example', 'group': 'acmd', 'help': 'Autocomplete-only helper'},
    ]))
    text = list(handler.server_help(''))[-1][1]
    assert '[File]' in text and '[system]' in text and '[Acmd]' in text
    assert 'private_rpc' not in text and 'acmd help example' not in text
    assert 'Aliases:' not in text and '\nacmd example' in text
    assert '[File]' in list(handler.server_help('client'))[-1][1]
    assert 'alias list' in list(handler.server_help('alias'))[-1][1]


def test_removed_commands_are_not_registered_or_claimed():
    assert SERVER_COMMAND_REGISTRY.get('disconnect') is None
    assert not hasattr(BuiltinCommandHandler, 'disconnect')
    handler = BuiltinCommandHandler.__new__(BuiltinCommandHandler)
    assert handler.resolve_builtin_command('disconnect', '') is None
    for command in ('interaction_demo', 'interaction_advanced_demo', 'interaction_preview_demo'):
        assert not hasattr(CommonCommands, command)
        assert not hasattr(CommonCommands.__new__(CommonCommands), command)
    assert all('|' not in item['help'] for item in SERVER_COMMAND_REGISTRY.candidates())
    assert next(item for item in SERVER_COMMAND_REGISTRY.candidates() if item['name'] == 'notify')['help'] == (
        'Run a Client command and notify when finished')


def test_gopin_list_has_no_machine_identifier_but_keeps_saved_paths():
    seen = []
    store = SimpleNamespace(list_items=lambda machine: (seen.append(machine) or [
        {'display_name': 'logs', 'path': '/tmp/logs'},
        {'display_name': 'projects', 'path': '/tmp/projects'},
    ]))
    support = PinnedPathBuiltinSupport(store, None,
        SimpleNamespace(session_info=SimpleNamespace(machine_id='host-identity')),
        None, None)
    status, text = list(support.gopin())[-1]
    assert status == 1
    assert text == 'logs -> /tmp/logs\nprojects -> /tmp/projects'
    assert seen == ['host-identity']


def test_client_native_help_uses_original_group_headers():
    owner = SimpleNamespace(_group_command_help_payload=lambda: {
        'shell': [('shell', 'Run shell command')],
        'file': [('download', 'Download a file')],
    })
    code, text = CommandIntrospectionMixin.help.__wrapped__(owner) if hasattr(
        CommandIntrospectionMixin.help, '__wrapped__') else CommandIntrospectionMixin.help(owner)
    assert code == 1
    assert '[Shell / Execution]' in text and '[File]' in text
