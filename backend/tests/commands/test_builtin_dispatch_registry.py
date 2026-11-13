"""Registered builtin call shapes, with no command-name routing exceptions."""
from types import MethodType

import pytest

from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


def _handler_with_stubs():
    from server.application.command.builtin_command_handler import BuiltinCommandHandler
    handler = BuiltinCommandHandler.__new__(BuiltinCommandHandler)
    calls = []
    for spec in SERVER_COMMAND_REGISTRY._commands.values():
        def record(self, *args, command_name=spec.name):
            calls.append((command_name, args))
            return iter([(1, 'ok')])
        setattr(handler, spec.handler, MethodType(record, handler))
    return handler, calls


@pytest.mark.parametrize('name,arg,expected', [
    ('script', '', ('list', '')),
    ('script', 'exec common/demo --name world', ('exec', 'common/demo --name world')),
    ('alias', 'set --platform common x = shell echo  hello', ('set', '--platform common x = shell echo  hello')),
    ('job', 'start demo --mode inproc --params "{}"', ('start', 'demo --mode inproc --params "{}"')),
])
def test_split_subcommands_use_registered_call_shape(name, arg, expected):
    handler, calls = _handler_with_stubs()
    assert list(handler.resolve_builtin_command(name, arg)) == [(1, 'ok')]
    assert calls == [(name, expected)]


@pytest.mark.parametrize('name,arg,expected', [
    ('history', '', 'list'),
    ('history', 'list', 'list'),
    ('history', 'run 12', 'run 12'),
    ('httpctl', '', 'help'),
    ('httpctl', 'resume --client-id offline-1', 'resume --client-id offline-1'),
    ('xt', '', 'help'),
    ('xt', 'help', 'help'),
    ('xt', 'exec ffmpeg -i "a b.mp4"', 'exec ffmpeg -i "a b.mp4"'),
    ('gopin', 'work', 'work'),
])
def test_raw_text_handlers_receive_registry_subcommand_and_unchanged_tail(name, arg, expected):
    handler, calls = _handler_with_stubs()
    assert list(handler.resolve_builtin_command(name, arg)) == [(1, 'ok')]
    assert calls == [(name, (expected,))]


def test_unknown_builtin_is_not_claimed_and_unknown_subcommand_is_error():
    handler, calls = _handler_with_stubs()
    assert handler.resolve_builtin_command('not-a-builtin', 'xyz') is None
    assert 'Unsupported xt subcommand' in list(handler.resolve_builtin_command('xt', 'bad'))[0][1]
    assert not calls


def test_history_explicit_list_matches_no_argument_form():
    from server.application.command.builtin_command_support import HistoryBuiltinSupport
    support = HistoryBuiltinSupport.__new__(HistoryBuiltinSupport)
    support._get_resolvable_quick_history = lambda: []
    assert list(support.history('')) == list(support.history('list'))


def test_registry_declares_split_invocation_and_reachable_xt_help():
    assert {spec.name for spec in SERVER_COMMAND_REGISTRY._commands.values()
            if spec.dispatch_subcommand} == {'script', 'alias', 'job'}
    assert SERVER_COMMAND_REGISTRY.parse('xt', '')[1:] == ('help', '')
    assert SERVER_COMMAND_REGISTRY.parse('xt', 'help')[1:] == ('help', '')
    with pytest.raises(ValueError, match='Unsupported xt subcommand'):
        SERVER_COMMAND_REGISTRY.parse('xt', 'unregistered')
