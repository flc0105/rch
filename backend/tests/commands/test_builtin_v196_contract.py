"""v1.96 public parser contracts, independent of optional Web dependencies."""
import json
from types import SimpleNamespace

import pytest

from core.protocol.result_envelope import ResultEnvelope
from core.utils.command_output import ResultDataShape, OutputFormat, render_result_payload
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY as REGISTRY


@pytest.mark.parametrize('command,arg,action,values', [
    ('script', '', 'list', {'json': False}),
    ('script', '--json', 'list', {'json': True}),
    ('script', 'view demo.py', 'view', {'name': 'demo.py'}),
    ('script', 'view --name demo.py', 'view', {'name': 'demo.py'}),
    ('script', 'exec --name demo --execution_mode inproc --output_mode stream -- --count 2 --tag value',
     'exec', {'name': 'demo', 'execution_mode': 'inproc', 'output_mode': 'stream',
              'params': {'count': '2', 'tag': 'value'}}),
    ('history', '', 'list', {'pinned': False}),
    ('history', 'list -p', 'list', {'pinned': True}),
    ('history', '--pinned', 'list', {'pinned': True}),
    ('history', 'list --pinned --json', 'list', {'pinned': True, 'json': True}),
    ('history', 'clear', 'clear', {'json': False}),
    ('history', 'run 3', 'run', {'index': 3}),
    ('history', 'run --index 3', 'run', {'index': 3}),
    ('watchdog', '', 'watchdog', {'json': False}),
    ('watchdog', '--json', 'watchdog', {'json': True}),
    ('rtt', '--json', 'rtt', {'json': True}),
    ('notify', 'whoami --json --option x', 'notify', {'command': 'whoami --json --option x'}),
    ('saveout', 'script exec demo -- --key 1 --key2 w', 'saveout',
     {'command': 'script exec demo -- --key 1 --key2 w'}),
])
def test_builtins_are_declarative(command, arg, action, values):
    invocation = REGISTRY.parse_invocation(command, arg)
    assert invocation.action == action
    for key, expected in values.items():
        assert invocation.arguments[key] == expected


@pytest.mark.parametrize('command,arg', [
    ('history', 'list --unknown'), ('history', 'run'), ('history', 'run --index banana'),
    ('history', 'run 1 --index 2'), ('history', 'run 2 --json'),
    ('history', 'list --pinned -p'), ('watchdog', '--unknown'),
    ('watchdog', '--json --json'), ('rtt', 'extra'), ('rtt', '-p'),
    ('script', 'list -p'), ('script', 'view --name'),
    ('script', 'exec demo --count 2'),
])
def test_undeclared_options_fail_in_shared_parser(command, arg):
    with pytest.raises(ValueError):
        REGISTRY.parse_invocation(command, arg)


def test_raw_tail_does_not_reinterpret_json_and_keeps_whitespace():
    raw = '  shell echo "a  b" --json --key 2'
    for command in ('saveout', 'notify'):
        inv = REGISTRY.parse_invocation(command, raw)
        assert inv.arguments['command'] == raw
        assert inv.output_format == OutputFormat.TEXT


def test_data_json_and_flat_table_are_same_underlying_data():
    data = {'state': 'running', 'count': 2}
    flat = ResultEnvelope(data=data, ).as_payload()
    assert json.loads(render_result_payload(flat, OutputFormat.JSON, view='data', shape='flat')) == data
    assert 'state' in render_result_payload(flat, OutputFormat.TEXT, view='data', shape='flat')
    rows = [{'index': 1, 'command': 'whoami', 'pinned': False}]
    table = ResultEnvelope(data=rows, ).as_payload()
    assert json.loads(render_result_payload(table, OutputFormat.JSON, view='data', shape='table')) == rows
    assert 'whoami' in render_result_payload(table, OutputFormat.TEXT, view='data', shape='table')
    assert json.loads(render_result_payload(ResultEnvelope(message='done').as_payload(), OutputFormat.JSON)) == {
        'status': 'success', 'message': 'done'}


def test_configuration_missing_key_error_is_not_wrapped_in_python_repr_quotes():
    from client.config.manager import ConfigurationManager
    from core.protocol.control import ConfigurationAction
    manager = ConfigurationManager(SimpleNamespace())
    scope = SimpleNamespace(_checkpoint=lambda: None, emit_progress=lambda *_args, **_kwargs: None)
    status, result = manager.execute(scope, ConfigurationAction.SET, {
        'key': 'NON_EXISTENT_RCH_TEST_KEY', 'value': '1', 'value_format': 'text'})
    assert status == 0
    assert result['message'] == 'Unknown or unsupported runtime config key: NON_EXISTENT_RCH_TEST_KEY'
    assert json.loads(render_result_payload(result, OutputFormat.JSON)) == {
        'status':'error', 'message': result['message']}
