"""ACMD-extracted option rules and migrated Server builtin argument contracts."""
import json
from types import SimpleNamespace

import pytest

from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.commands.argument_parser import parse_argument_text
from core.protocol.result_envelope import ResultEnvelope
from core.utils.command_output import ResultDataShape, render_result_payload
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY


def invocation(name, text):
    return SERVER_COMMAND_REGISTRY.parse_invocation(name, text)


@pytest.mark.parametrize('text', ['', 'list', 'list --json', '--json'])
def test_job_default_list_and_json(text):
    parsed = invocation('job', text)
    assert parsed.action == 'list'
    assert parsed.arguments['json'] == ('--json' in text)


@pytest.mark.parametrize('text', [
    'start example_monitor --mode subprocess -- --interval_seconds 2',
    'start --name example_monitor --mode subprocess -- --interval_seconds 2',
    'start --mode=subprocess --name=example_monitor -- --interval_seconds=2',
])
def test_job_named_and_positional_are_same_request(text):
    args = invocation('job', text).arguments
    assert args['name'] == 'example_monitor'
    assert args['mode'] == 'subprocess'
    assert args['params'] == {'interval_seconds': '2'}


def test_job_repeated_params_support_spaces_and_embedded_flag_as_value():
    data = invocation('job', 'start demo --json -- --greeting "hello  world" '
                             '--literal=--json')
    assert data.output_format == 'json'
    assert data.arguments['params'] == {'greeting': 'hello  world', 'literal': '--json'}


@pytest.mark.parametrize('text', [
    'start demo --params "{}"', 'start demo --param key',
    'start demo -- --key', 'start demo -- --key 1 --key 2',
    'start demo -- --key 1 stray', 'start demo -- --key 1 --bad',
    'start demo --name other', 'start --name demo other',
    'start demo --mode x --mode y', 'ps extra', 'stop',
    'stop-all --name any', 'logs demo --json', 'list --json --json',
])
def test_job_invalid_syntax_rejected_before_domain(text):
    with pytest.raises(ValueError):
        invocation('job', text)


@pytest.mark.parametrize('command,text', [
    ('start', 'demo'), ('stop', 'demo'), ('status', '--name demo'),
    ('logs', 'demo -f'), ('logs', '--name demo --follow')])
def test_job_name_options_or_positionals(command, text):
    parsed = invocation('job', command + ' ' + text)
    assert parsed.arguments['name'] == 'demo'
    if command == 'logs':
        assert parsed.arguments['follow'] is True


@pytest.mark.parametrize('text', ['', 'list', 'list --json', '--json'])
def test_config_defaults_to_list(text):
    assert invocation('config', text).action == 'list'


@pytest.mark.parametrize('text', [
    'set KEY "hello world"',
    'set --key KEY --value "hello world"',
    'set KEY --value "hello world"',
    'set --key KEY "hello world"',
    'set --value "hello world" --key KEY',
])
def test_config_named_and_positional_mixing(text):
    assert {k: v for k, v in invocation('config', text).arguments.items() if k != 'json'} == {
        'key': 'KEY', 'value': 'hello world'}


def test_config_windows_path_remains_literal():
    parsed = SERVER_COMMAND_REGISTRY.parse_invocation('config',
        r'set --key SCRIPT_PYTHON_PATH --value "C:\Program Files\Python312\python.exe"',
        literal_backslashes=True)
    assert parsed.arguments['value'] == r'C:\Program Files\Python312\python.exe'


@pytest.mark.parametrize('text', ['--all', 'list --all', 'set KEY --json',
                                 'set KEY VALUE EXTRA', 'reset KEY VALUE',
                                 'reset-all KEY', 'set KEY VALUE --params "{}"'])
def test_config_removed_syntax_not_accepted(text):
    with pytest.raises(ValueError):
        invocation('config', text)


def test_acmd_validator_is_shared_with_server_parser():
    schema = ArgumentCommandSpec('example', options=[
        ArgumentOptionSpec('name', required=True, positional_index=0),
        ArgumentOptionSpec('enabled', option_type='bool', default=False),
        ArgumentOptionSpec('verbose', option_type='flag', default=False, alias='v'),
    ])
    assert parse_argument_text(schema, 'sample --enabled true -v') == {
        'name': 'sample', 'enabled': True, 'verbose': True}
    with pytest.raises(ValueError, match='Duplicate'):
        parse_argument_text(schema, 'sample --verbose -v')
    assert parse_argument_text(schema, '-- --json')['name'] == '--json'


def test_other_server_builtins_are_not_reinterpreted():
    names = set(SERVER_COMMAND_REGISTRY._commands)
    assert len(names) == 14 and 'set' not in names and 'config' in names
    for root, raw, expected_sub, expected_tail in [
        ('alias', 'set a = shell echo --json', 'set', 'a = shell echo --json'),
        ('script', 'exec common/demo -- --name world', 'exec', 'common/demo -- --name world'),
        ('xt', 'exec ffmpeg -i "a b.mp4"', 'exec', 'ffmpeg -i "a b.mp4"'),
        ('history', 'run 12', 'run', '12'),
    ]:
        spec, sub, tail = SERVER_COMMAND_REGISTRY.parse(root, raw)
        assert (sub, tail) == (expected_sub, expected_tail)
        if root in ('alias', 'xt'):
            assert not spec.structured


@pytest.mark.parametrize('text', [
    'exec ops/demo --execution_mode inproc --output_mode stream -- --key 1 --key2 w',
    'exec --name ops/demo --execution_mode=inproc --output_mode=stream -- --key 1 --key2=w',
])
def test_script_cli_dynamic_arguments_after_separator(text):
    result = invocation('script', text)
    assert result.action == 'exec'
    assert result.arguments == {
        'name': 'ops/demo', 'execution_mode': 'inproc', 'output_mode': 'stream',
        'params': {'key': '1', 'key2': 'w'},
    }


def test_real_script_metadata_accepts_delimited_typed_params():
    from pathlib import Path
    from server.application.scripts.script_run_service import prepare_script_control

    root = Path(__file__).resolve().parents[2] / 'server' / 'resources' / 'scripts'
    parsed = invocation('script',
        'exec --name test/misc/script_mode_probe --execution_mode subprocess_pipe '
        '--output_mode collect -- --count 2 --delay 0')
    payload = prepare_script_control(str(root), parsed.arguments['name'],
                                     parsed.arguments['params'],
                                     config={'items': [
                                         {'key': 'SCRIPT_DEFAULT_EXECUTION_MODE', 'value': 'inproc', 'choices': ['inproc', 'subprocess_pipe']},
                                         {'key': 'SCRIPT_DEFAULT_OUTPUT_MODE', 'value': 'collect', 'choices': ['collect', 'stream']},
                                     ]},
                                     execution_mode=parsed.arguments['execution_mode'],
                                     output_mode=parsed.arguments['output_mode'])
    assert payload['params'] == {'count': 2, 'delay': 0}
    assert payload['execution_mode'] == 'subprocess_pipe'
    assert payload['output_mode'] == 'collect'


def test_script_view_accepts_named_or_positional_name():
    assert invocation('script', 'view ops/demo').arguments == {'name': 'ops/demo'}
    assert invocation('script', 'view --name ops/demo').arguments == {'name': 'ops/demo'}
    assert invocation('script', 'list --json').output_format == 'json'
    assert invocation('script', '--json').action == 'list'


@pytest.mark.parametrize('root,text', [
    ('script', 'exec ops/demo --key 1'),
    ('script', 'exec ops/demo -- --key'),
    ('script', 'exec ops/demo -- --key 1 --key 2'),
    ('script', 'exec ops/demo -- --key 1 extra'),
    ('script', 'exec ops/demo --name other'),
    ('script', 'exec ops/demo -- --json'),
    ('script', 'view --name demo extra'),
    ('script', 'view demo --output_mode stream'),
    ('job', 'start demo --interval_seconds 2'),
    ('job', 'start demo -- --interval_seconds 2 --interval_seconds 3'),
    ('job', 'start demo -- --interval_seconds 2 extra'),
])
def test_dynamic_and_regular_option_boundary_enforced(root, text):
    with pytest.raises(ValueError):
        invocation(root, text)


def test_builtin_json_is_not_consumed_from_dynamic_tail():
    result = invocation('job', 'start demo -- --json true')
    assert result.output_format == 'text'
    assert result.arguments['params'] == {'json': 'true'}
    script = invocation('script', 'exec --name demo -- --name Alice')
    assert script.arguments['name'] == 'demo'
    assert script.arguments['params'] == {'name': 'Alice'}
    with pytest.raises(ValueError):
        invocation('job', 'start demo --param foo bar')


def test_job_start_delimited_params_are_forwarded_to_control():
    from types import SimpleNamespace
    from server.application.command.job_builtin_support import JobBuiltinSupport
    from core.protocol.control import JobAction

    support = JobBuiltinSupport(
        None, SimpleNamespace(session_info=SimpleNamespace(client_id='client-a')),
        None,
        SimpleNamespace(prepare_job_start=lambda _client, _name, mode: mode),
        None,
    )
    support._send = lambda action, **kwargs: iter([(1, (action, kwargs))])
    request = invocation('job', 'start example_monitor --mode subprocess -- --interval_seconds 2')
    assert list(support.execute_subcommand(request)) == [(1, (
        JobAction.START,
        {'output_format': 'text', 'job_name': 'example_monitor',
         'params': {'interval_seconds': '2'}, 'execution_mode': 'subprocess'},
    ))]


def test_result_envelope_has_one_source_but_two_presentation_formats():
    payload = ResultEnvelope(data={'a': 1, 'b': 2}, 
                             ).as_payload()
    assert payload['status'] == 'success'
    assert json.loads(render_result_payload(payload, 'json', view='data', shape='flat')) == {'a': 1, 'b': 2}
    assert render_result_payload(payload, view='data', shape='flat').splitlines() == ['a                   1', 'b                   2']
    table = ResultEnvelope(data=[{'a': 1, 'b': 2}], 
                           ).as_payload()
    assert json.loads(render_result_payload(table, 'json', view='data', shape='table')) == [{'a': 1, 'b': 2}]
    assert 'a' in render_result_payload(table, view='data', shape='table') and 'b' in render_result_payload(table, view='data', shape='table')
    message = ResultEnvelope(message='Updated.').as_payload()
    assert render_result_payload(message) == 'Updated.'
    assert json.loads(render_result_payload(message, 'json')) == {'status': 'success', 'message': 'Updated.'}


def test_every_structured_builtin_leaf_owns_its_argument_schema():
    for spec in SERVER_COMMAND_REGISTRY._commands.values():
        if spec.structured and spec.subcommands:
            assert all(child.argument_spec is not None or child.raw_tail for child in spec.subcommands)
        elif spec.structured:
            assert spec.argument_spec is not None or spec.raw_tail
        else:
            assert all(child.argument_spec is None for child in spec.subcommands)
