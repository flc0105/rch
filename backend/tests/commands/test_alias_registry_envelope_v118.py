"""Alias is a registered typed builtin; only the RHS of '=' is business grammar."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.protocol.message_queue import ResultChunk
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from tests.commands.test_alias_grouped_schema import _alias_manager_class


def _alias_support_class():
    # Isolate this class to test its real implementation without importing the
    # unrelated Server/Web bootstrap (which requires Flask/Werkzeug).
    filename = Path(__file__).resolve().parents[2] / 'server/application/command/builtin_command_support.py'
    module = ast.parse(filename.read_text(encoding='utf-8'), str(filename))
    node = next(node for node in module.body if isinstance(node, ast.ClassDef)
                and node.name == 'AliasBuiltinSupport')
    scope = {'ResultChunk': ResultChunk}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(filename), 'exec'), scope)
    return scope['AliasBuiltinSupport']


@pytest.fixture
def alias_support(tmp_path):
    manager = _alias_manager_class().__new__(_alias_manager_class())
    manager.alias_path = str(tmp_path / 'aliases.json')
    manager.aliases = manager._create_empty_aliases()
    manager._file_signature = None
    return _alias_support_class()(manager, SimpleNamespace(session_info=SimpleNamespace(os_alias='mac')))


def invoke(support, text):
    return next(support.alias(SERVER_COMMAND_REGISTRY.parse_invocation('alias', text)))


@pytest.mark.parametrize('text,platform,name,definition', [
    ('set sample = shell echo "a  b" --json x=y', None, 'sample', '= shell echo "a  b" --json x=y'),
    ('set --platform=mac sample=shell echo "a  b" --json x=y', 'mac', 'sample', '=shell echo "a  b" --json x=y'),
    ('set --name sample -p=linux = shell echo x=y', 'linux', 'sample', '= shell echo x=y'),
    ('set sample --platform win = shell echo yes', 'win', 'sample', '= shell echo yes'),
])
def test_registry_parses_fixed_parts_and_keeps_opaque_definition(text, platform, name, definition):
    invocation = SERVER_COMMAND_REGISTRY.parse_invocation('alias', text)
    assert invocation.action == 'set'
    assert invocation.arguments == {'name': name, 'platform': platform, 'definition': definition}


def test_alias_set_list_unset_real_persistence_and_envelope(alias_support):
    saved = invoke(alias_support, 'set --platform=mac sample=shell echo "a  b" --json x=y')
    assert saved[0] == 1 and saved.event == {
        'event_type': 'completed', 'status': 'success', 'message': 'Alias saved [mac]: sample'}
    assert alias_support.alias_manager.get_alias_definition('sample', 'mac') == 'shell echo "a  b" --json x=y'
    listed = invoke(alias_support, '--json')
    assert listed[0] == 1 and listed.event['event_type'] == 'completed'
    assert json.loads(listed[1]) == [{'platform': 'mac', 'alias': 'sample', 'command': 'shell echo "a  b" --json x=y'}]
    assert listed.event['data'] == json.loads(listed[1])
    removed = invoke(alias_support, 'unset sample -p mac')
    assert removed.event == {'event_type': 'completed', 'status': 'success', 'message': 'Alias removed [mac]: sample'}
    assert json.loads(invoke(alias_support, '--json')[1]) == []
    assert alias_support.alias_manager.alias_path and Path(alias_support.alias_manager.alias_path).exists()


def test_default_common_scope_does_not_change_platform_override(alias_support):
    assert invoke(alias_support, 'set -p mac foo=shell echo mac')[0] == 1
    assert invoke(alias_support, 'set foo = shell echo common')[0] == 1
    assert alias_support.alias_manager.get_alias_definition('foo', 'common') == 'shell echo common'
    assert alias_support.alias_manager.get_alias_definition('foo', 'mac') == 'shell echo mac'
    assert invoke(alias_support, 'unset foo')[0] == 1
    assert alias_support.alias_manager.get_alias_definition('foo', 'mac') == 'shell echo mac'


@pytest.mark.parametrize('text', [
    'set --platform nope name = echo hi', 'set name', 'set name=',
    'unset --platform no-such name', 'unset nonexistent',
])
def test_business_failure_is_authoritative_result_envelope(alias_support, text):
    item = invoke(alias_support, text)
    assert item[0] == 0 and item.terminal_authoritative
    assert item.event['status'] == 'error' and item.event['event_type'] == 'completed'
    assert item.event['message'] == item[1]


@pytest.mark.parametrize('text', [
    'list --platform mac', 'list extra', 'set --unexpected x = echo hi',
    'unset --json x', 'unset x y', 'set x --name other = shell echo hi',
])
def test_registry_rejects_wrong_fixed_syntax_before_alias_business(text):
    with pytest.raises(ValueError):
        SERVER_COMMAND_REGISTRY.parse_invocation('alias', text)


def test_completion_and_help_share_registered_alias_actions():
    registry = SERVER_COMMAND_REGISTRY
    assert {'alias list', 'alias set ', 'alias unset '} <= {
        name for name, _ in registry.completion_paths('alias')}
    assert 'alias set' in registry.help('alias')
    assert 'alias set' in registry.help('alias set')
