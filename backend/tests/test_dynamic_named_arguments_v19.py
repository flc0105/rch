"""Shared named argument lexical boundaries after -- delimiter."""
import pytest
from core.commands.argument_parser import _parse_named_tail
from core.commands.argument_errors import ArgumentCommandValidationError


def test_named_values_may_begin_with_double_dash():
    assert _parse_named_tail(['--name', '--danger', '--operation', 'inspect']) == {'name': '--danger', 'operation': 'inspect'}
    assert _parse_named_tail(['--name=--danger']) == {'name': '--danger'}


def test_duplicate_and_missing_named_values_still_fail():
    with pytest.raises(ArgumentCommandValidationError, match='Duplicate'):
        _parse_named_tail(['--name', 'first', '--name', 'second'])
    with pytest.raises(ArgumentCommandValidationError, match='requires a value'):
        _parse_named_tail(['--name'])
    with pytest.raises(ArgumentCommandValidationError, match='Expected named argument'):
        _parse_named_tail(['--name', 'value', 'extra'])


def test_script_exec_uses_shared_parser_for_double_dash_values():
    from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
    for tail in ('exec test/misc/json_result_actions_update -- --name "--danger"',
                 'exec test/misc/json_result_actions_update -- --name=--danger'):
        invocation = SERVER_COMMAND_REGISTRY.parse_invocation('script', tail)
        assert invocation.arguments['params'] == {'name': '--danger'}
