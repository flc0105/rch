"""One data model and text layout contract for Server Builtins and Client ACMD."""
import json
from types import SimpleNamespace

import pytest

from core.protocol.message_queue import ResultChunk
from core.protocol.result_envelope import ResultEnvelope
from core.utils.command_output import (
    ResultDataShape, StructuredCommandResult, render_result_payload,
    render_structured_result, resolve_presentation,
)
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY as registry
from server.application.command.configuration_builtin_support import ConfigurationBuiltinSupport
from server.application.command.external_tool_cli_builtin_support import ExternalToolCliBuiltinSupport


ROWS = [
    {'name': 'alpha', 'description': '很长的说明\n第二行', 'enabled': True},
    {'name': 'beta', 'description': 'short', 'enabled': False},
]


def _payload(rows=ROWS):
    return ResultEnvelope(data=rows).as_payload()


@pytest.mark.parametrize('shape', ['lines', 'table', 'records', 'kv', 'numbered', 'grouped'])
def test_server_and_acmd_share_exact_renderer(shape):
    data = ([{'index': 11, 'name': 'alpha', 'description': 'one', 'group': 'A'},
             {'index': 14, 'name': 'beta', 'description': 'two', 'group': 'B'}])
    arguments = dict(shape=shape, line_field='name', key_field='name',
                     value_field='description', number_field='index',
                     number_value_field='name')
    a = render_result_payload(_payload(data), view='data', **arguments)
    result = StructuredCommandResult(1, data, **arguments)
    b = render_structured_result(result)[1]
    assert a == b
    assert json.loads(render_result_payload(_payload(data), 'json', view='data', **arguments)) == data
    assert json.loads(render_structured_result(result, 'json')[1]) == data


def test_records_are_vertical_lossless_and_do_not_mutate_data():
    data = [dict(row) for row in ROWS]
    before = json.dumps(data, ensure_ascii=False)
    text = render_result_payload(_payload(data), view='data', shape='records')
    assert text.startswith('---\nname: alpha\ndescription: 很长的说明\n  第二行\nenabled: True')
    assert text.count('---') == 2
    assert json.dumps(data, ensure_ascii=False) == before
    assert json.loads(render_result_payload(_payload(data), 'json', view='data', shape='records')) == data


def test_flat_is_a_peer_layout_and_kv_is_distinct():
    data = {'id': 3, 'status': 'running'}
    flat = render_result_payload(_payload(data), view='data', shape=ResultDataShape.FLAT, width=12)
    kv = render_result_payload(_payload(data), view='data', shape='kv')
    assert flat.startswith('id') and 'running' in flat
    assert kv == 'id = 3\nstatus = running'
    assert json.loads(render_result_payload(_payload(data), 'json', view='data', shape='kv')) == data


def test_numbered_uses_actual_indices_and_grouped_list_uses_names():
    data = [{'index': 12, 'command': 'first'}, {'index': 37, 'command': 'second'}]
    assert render_result_payload(_payload(data), view='data', shape='numbered') == ' 12  first\n 37  second'
    data2 = [{'group': 'network', 'key': 'mode', 'value': 'auto'},
             {'group': 'system', 'key': 'debug', 'value': False}]
    rendered = render_result_payload(_payload(data2), view='data', shape='grouped',
                                     key_field='key', value_field='value')
    assert rendered == '[network]\nmode = auto\n\n[system]\ndebug = False'


def test_json_precedence_and_format_validation():
    output, shape = resolve_presentation({'json': True, 'format': 'records'}, 'lines')
    assert output == 'json' and shape == 'lines'
    assert resolve_presentation({'format': 'json'}, 'lines')[0] == 'json'
    assert resolve_presentation({'format': 'records'}, 'lines')[1] == 'records'
    assert resolve_presentation({}, 'lines')[1] == 'lines'
    with pytest.raises(ValueError, match='Invalid --format'):
        resolve_presentation({'format': 'unsupported'}, 'lines')
    with pytest.raises(ValueError, match='requires an object'):
        render_result_payload(_payload(ROWS), view='data', shape='flat')
    with pytest.raises(ValueError, match='requires an array'):
        render_result_payload(_payload({'name': 'a'}), view='data', shape='records')
    with pytest.raises(ValueError, match='requires declared key and value fields'):
        render_result_payload(_payload(ROWS), view='data', shape='kv')
    with pytest.raises(ValueError, match='requires declared field: index'):
        render_result_payload(_payload(ROWS), view='data', shape='numbered')



@pytest.mark.parametrize('command,tail,action,supported,unsupported', [
    ('script', 'list', 'list', 'records', 'numbered'),
    ('job', 'list', 'list', 'table', 'kv'),
    ('alias', 'list', 'list', 'kv', 'numbered'),
    ('config', 'list', 'list', 'kv', 'numbered'),
    ('history', 'list', 'list', 'numbered', 'kv'),
    ('gopin', 'list', 'list', 'records', 'numbered'),
    ('watchdog', '', 'watchdog', 'grouped', 'records'),
    ('rtt', '', 'rtt', 'flat', 'table'),
    ('xt', 'exec list', 'exec.list', 'lines', 'kv'),
    ('xt', 'package list', 'package.list', 'records', 'flat'),
    ('xt', 'module list package', 'module.list', 'table', 'numbered'),
    ('xt', 'instance list', 'instance.list', 'records', 'grouped'),
    ('xt', 'exec info example', 'exec.info', 'flat', 'records'),
    ('job', 'ps', 'ps', 'table', 'numbered'),
    ('job', 'status demo', 'status', 'kv', 'records'),
])
def test_server_query_spec_declares_compatible_formats(command, tail, action, supported, unsupported):
    value = registry.parse_invocation(command, f'{tail} -f {supported}')
    assert value.action == action and value.arguments['format'] == supported
    assert registry.parse_invocation(command, f'{tail} --format json').output_format == 'json'
    assert registry.parse_invocation(command, f'{tail} --format json --json').output_format == 'json'
    for invalid in (unsupported, 'unknown-layout'):
        with pytest.raises(ValueError, match='Unsupported --format value'):
            registry.parse_invocation(command, f'{tail} --format {invalid}')



def test_xt_list_uses_one_data_source_and_preserves_columns():
    support = ExternalToolCliBuiltinSupport.__new__(ExternalToolCliBuiltinSupport)
    support._build_cli_list_payload = lambda: [
        {'exec_name': 'curl', 'package_id': 'net'}, {'exec_name': 'grep', 'package_id': 'text'}]
    run = lambda args: support._render_cli_list(registry.parse_invocation('xt', f'exec list {args}').arguments)
    assert run('')[1] == 'curl\ngrep'
    assert 'EXEC' in run('--format table')[1] and 'PACKAGE' in run('--format table')[1]
    assert 'exec_name: curl' not in run('--format records')[1]  # projected display header
    assert 'EXEC: curl' in run('--format records')[1]
    expected = [{'exec_name': 'curl', 'package_id': 'net'}, {'exec_name': 'grep', 'package_id': 'text'}]
    assert json.loads(run('--json')[1]) == expected
    assert json.loads(run('--format table --json')[1]) == expected


def test_xt_package_table_yes_no_and_json_boolean_are_separate():
    support = ExternalToolCliBuiltinSupport.__new__(ExternalToolCliBuiltinSupport)
    rows = [{'package_id': 'net', 'display_name': 'Network', 'installed': True},
            {'package_id': 'tools', 'display_name': 'Tools', 'installed': False}]
    invocation = registry.parse_invocation('xt', 'package list --format table')
    output = support._render_rows(rows, invocation.arguments, line_field='package_id',
        columns=(('package_id', 'PACKAGE'), ('display_name', 'NAME'), ('installed', 'INSTALLED')),
        text_values={'installed': {True: 'yes', False: 'no'}})
    assert 'yes' in output[1] and 'no' in output[1]
    invocation = registry.parse_invocation('xt', 'package list --format json')
    output = support._render_rows(rows, invocation.arguments, line_field='package_id',
        columns=(('package_id', 'PACKAGE'), ('display_name', 'NAME'), ('installed', 'INSTALLED')),
        text_values={'installed': {True: 'yes', False: 'no'}})
    assert json.loads(output[1]) == rows


def test_config_grouped_default_and_table_json_options():
    support = ConfigurationBuiltinSupport.__new__(ConfigurationBuiltinSupport)
    control_result = ResultEnvelope(data={'items': [
        {'group': 'system', 'key': 'mode', 'value': 'auto', 'default_value': 'manual'},
        {'group': 'network', 'key': 'timeout', 'value': 20, 'default_value': 30},
    ]}).as_payload()
    support._send = lambda *_: iter([ResultChunk(1, control_result, True, event=control_result)])
    run = lambda tail: next(support.config(registry.parse_invocation('config', tail)))
    assert '[network]\ntimeout = 20' in run('list')[1]
    assert run('list --format kv')[1] == 'timeout = 20\nmode = auto'
    assert run('list -f kv')[1] == run('list --format kv')[1]
    assert 'default' in run('list --format table')[1]
    assert 'group: network' in run('list --format records')[1]
    rows = json.loads(run('list --json')[1])
    assert rows[0]['default'] == 30
    assert json.loads(run('list --format table --json')[1]) == rows
    assert json.loads(run('list -f json')[1]) == rows
    assert json.loads(run('list --format kv --json')[1]) == rows


def test_config_kv_never_rewrites_real_config_keys():
    support = ConfigurationBuiltinSupport.__new__(ConfigurationBuiltinSupport)
    control_result = ResultEnvelope(data={'items': [
        {'group': 'command', 'key': 'COMMAND_DEFAULT_SHELL_TIMEOUT',
         'value': 60, 'default_value': 30},
        {'group': 'connection', 'key': 'RECONNECT_INTERVAL_SECONDS',
         'value': 5, 'default_value': 10},
        {'group': 'preview', 'key': 'PREVIEW_IMAGE_COMPRESS_ENABLED',
         'value': False, 'default_value': True},
    ]}).as_payload()
    support._send = lambda *_: iter([ResultChunk(1, control_result, True, event=control_result)])
    run = lambda tail: next(support.config(registry.parse_invocation('config', tail)))
    assert run('list --format kv')[1] == (
        'COMMAND_DEFAULT_SHELL_TIMEOUT = 60\n'
        'RECONNECT_INTERVAL_SECONDS = 5\n'
        'PREVIEW_IMAGE_COMPRESS_ENABLED = False'
    )
    assert '[command]\nCOMMAND_DEFAULT_SHELL_TIMEOUT = 60' in run('list')[1]
    assert 'group' in run('list --format table')[1]
    rows = json.loads(run('list --format json')[1])
    assert rows[0] == {'group': 'command', 'key': 'COMMAND_DEFAULT_SHELL_TIMEOUT',
                       'value': 60, 'default': 30}


def test_acmd_display_options_are_parsed_by_client_and_forwarded_verbatim():
    from client.commands.acmd.standalone import ps, netstat, ifconfig, python_packages, drives, launchd
    from server.application.command.command_planner import CommandPlanner
    for module, spec_name in [
        (ps, 'PS_ARGUMENT_SPEC'), (netstat, 'NETSTAT_ARGUMENT_SPEC'),
        (ifconfig, 'IFCONFIG_ARGUMENT_SPEC'), (python_packages, 'PYTHON_PACKAGES_SPEC'),
        (drives, 'DRIVES_SPEC'), (launchd, 'LAUNCHD_ARGUMENT_SPEC'),
    ]:
        spec = getattr(module, spec_name)
        assert 'format' not in {option.name for option in spec.options}
        assert 'json' not in {option.name for option in spec.options}
    planner = CommandPlanner(alias_manager=None, plan_executor=lambda plan: plan, error_executor=None)
    for spelling in ('--format records', '-f records', '--format=records'):
        command = 'acmd ps ' + spelling
        plan = planner.build_argument_command_plan(command)
        assert plan['command'] == plan['extra']['raw'] == command
        assert 'presentation_format' not in plan
        assert ('format' in plan['extra']['args'] or 'f' in plan['extra']['args'])
    assert planner.build_argument_command_plan('acmd ps --json')['extra']['args']['json'] is True

def test_watchdog_default_grouped_flat_rejected_and_json_untouched():
    support = ConfigurationBuiltinSupport.__new__(ConfigurationBuiltinSupport)
    data = {'service': {'running': True, 'last_check': 'now'}, 'worker': {'status': 'ok'}}
    event = ResultEnvelope(data=data).as_payload()
    support._send = lambda *_: iter([ResultChunk(1, event, True, event=event)])
    run = lambda tail: next(support.watchdog(registry.parse_invocation('watchdog', tail)))
    assert '[service]' in run('')[1]
    assert 'running = True' in run('')[1]
    assert json.loads(run('--json')[1]) == data
    assert json.loads(run('--format json')[1]) == data
    with pytest.raises(ValueError, match='Unsupported --format value'):
        run('--format records')


def test_history_numbered_and_detail_json_keep_stored_indices():
    # The history support module is loaded lazily below because Server config has
    # optional Flask dependencies that are not required by this renderer test.
    import importlib
    import sys
    import types
    from unittest.mock import patch

    config = types.ModuleType('server.config.config')
    config.COMMAND_HISTORY_RECENT_LIMIT = 100
    config.SCRIPT_PATH = '/unused/scripts'
    config.ALIAS_PATH = '/unused/aliases.json'
    history = types.ModuleType('server.application.history.quick_history')
    history.QuickHistoryRecordPolicy = type('QuickHistoryRecordPolicy', (), {})
    name = 'server.application.command.builtin_command_support'
    with patch.dict(sys.modules, {'server.config.config': config,
                                  'server.application.history.quick_history': history}):
        sys.modules.pop(name, None)
        module = importlib.import_module(name)
        support = module.HistoryBuiltinSupport.__new__(module.HistoryBuiltinSupport)
        support._get_resolvable_quick_history = lambda: [
            {'index': 4, 'command': 'acmd ps', 'is_pinned': False},
            {'index': 18, 'command': 'help client', 'is_pinned': True}]
        run = lambda tail: next(support.history(registry.parse_invocation('history', tail)))
        assert '  4  acmd ps' in run('')[1]
        assert ' 18  help client' in run('')[1]
        assert 'Tip: use history run' in run('')[1]
        assert 'index' in run('--format table')[1]
        assert 'command: acmd ps' in run('--format records')[1]
        data = json.loads(run('--json')[1])
        assert [row['index'] for row in data] == [4, 18]
        assert json.loads(run('--format json')[1]) == data
        sys.modules.pop(name, None)


def test_acmd_ps_native_json_preserves_action_payload(monkeypatch):
    from client.commands.acmd.standalone import ps as command
    from core.commands.argument_validator import ArgumentCommandValidator
    from client.runtime.execution.process.process_service import ProcessService
    from core.utils.command_output import project_result_chunks
    from core.protocol.result_envelope import result_wire_event
    monkeypatch.setattr(ProcessService, 'list_processes', lambda *_: [
        {'pid': 98, 'ppid': 1, 'name': 'python', 'username': 'a', 'status': 'running'}])
    args = ArgumentCommandValidator().normalize(command.PS_ARGUMENT_SPEC, {'with-actions': True})
    result = command.ps(object(), args)
    assert isinstance(result, StructuredCommandResult)
    assert result.formats == ('table', 'records', 'json')
    assert result.data[0]['_actions'][0]['refresh'] is True
    def show(fmt):
        wire = result_wire_event(100, result.status, result.as_event(requested=fmt))
        entry = ResultChunk(1, wire, True, event=wire)
        return next(project_result_chunks([entry]))[1]
    assert json.loads(show('json')) == result.data
    assert 'pid: 98' in show('records')
    assert '_actions' not in show('table')

def test_acmd_python_packages_loaded_is_same_data_all_layouts(monkeypatch):
    from client.commands.acmd.standalone import python_packages as command
    from core.commands.argument_validator import ArgumentCommandValidator
    from core.utils.command_output import project_result_chunks
    from core.protocol.result_envelope import result_wire_event
    monkeypatch.setattr(command.metadata, 'packages_distributions', lambda: {'json': ['stdlib'], 'fakepkg': ['fake']})
    args = ArgumentCommandValidator().normalize(command.PYTHON_PACKAGES_SPEC, {'loaded': True})
    from unittest.mock import patch
    with patch.dict(command.sys.modules, {'fakepkg': object()}):
        result = command.python_packages(object(), args)
    assert result.formats == ('lines', 'table', 'records', 'json')
    def show(fmt):
        wire = result_wire_event(100, result.status, result.as_event(requested=fmt))
        entry = ResultChunk(1, wire, True, event=wire)
        return next(project_result_chunks([entry]))[1]
    assert show(None) == 'fakepkg\njson'
    assert 'module' in show('table')
    assert 'module: fakepkg' in show('records')
    assert json.loads(show('json')) == result.data 

def test_format_declared_in_help_and_static_completion():
    assert 'format' in registry.help('script list')
    assert '--format' in registry.help('config list')
    candidates = [text for text, _ in registry.static_completion_candidates('script')]
    assert 'script list --format ' in candidates
    from client.commands.acmd.help import ArgumentCommandHelpBuilder
    from client.commands.acmd.standalone.ps import PS_ARGUMENT_SPEC
    assert '--format' in ArgumentCommandHelpBuilder().build(PS_ARGUMENT_SPEC)


def test_key_value_composite_keys_preserve_group_identity():
    rows = [
        {'group': 'network', 'key': 'timeout', 'value': 30, 'default': 60},
        {'group': 'storage', 'key': 'timeout', 'value': 10, 'default': 20},
    ]
    options = dict(key_field=('group', 'key'), value_field='value')
    text = render_result_payload(_payload(rows), view='data', shape='kv', **options)
    assert text == 'network.timeout = 30\nstorage.timeout = 10'
    assert render_structured_result(StructuredCommandResult(1, rows, shape='kv', **options))[1] == text
    assert json.loads(render_result_payload(_payload(rows), 'json', view='data', shape='kv', **options)) == rows
    with pytest.raises(ValueError, match='declared field: missing'):
        render_result_payload(_payload(rows), view='data', shape='kv',
                              key_field=('group', 'missing'), value_field='value')


def test_config_lines_are_qualified_and_alias_grouped_reuses_platform_field():
    from core.utils.command_output import render_result_payload
    configs = [{'group': 'network', 'key': 'timeout', 'value': 30, 'default': 60}]
    text = render_result_payload(_payload(configs), view='data', shape='lines',
                                 line_field=('group', 'key'), line_separator='.')
    assert text == 'network.timeout'
    aliases = [{'platform': 'common', 'alias': 'll', 'command': 'shell ls -la'},
               {'platform': 'mac', 'alias': 'psx', 'command': 'acmd ps'}]
    text = render_result_payload(_payload(aliases), view='data', shape='grouped',
                                 group_field='platform', key_field='alias', value_field='command')
    assert '[common]\nll = shell ls -la' in text
    assert '[mac]\npsx = acmd ps' in text
    assert render_result_payload(_payload(aliases), view='data', shape='lines',
                                 line_field='alias') == 'll\npsx'

@pytest.mark.parametrize('layout,options,diagnostic', [
    ('lines', {}, 'explicitly declared display field'),
    ('kv', {}, 'declared key and value fields'),
    ('numbered', {}, 'declared field: index'),
    ('grouped', {'key_field': 'name', 'value_field': 'description'}, 'declared field: group'),
])
def test_renderer_never_invents_mapping_or_numbering(layout, options, diagnostic):
    with pytest.raises(ValueError, match=diagnostic):
        render_result_payload(_payload(ROWS), view='data', shape=layout, **options)


def test_numbered_requires_integer_unique_real_ids():
    for rows, diagnostic in [
        ([{'index': '1', 'command': 'echo hello'}], 'integer identifiers'),
        ([{'index': 2, 'command': 'one'}, {'index': 2, 'command': 'two'}], 'unique identifiers'),
    ]:
        with pytest.raises(ValueError, match=diagnostic):
            render_result_payload(_payload(rows), view='data', shape='numbered')


def test_grouped_never_overwrites_duplicate_keys():
    rows = [{'group': 'network', 'key': 'timeout', 'value': 1},
            {'group': 'network', 'key': 'timeout', 'value': 2}]
    with pytest.raises(ValueError, match='duplicate key'):
        render_result_payload(_payload(rows), view='data', shape='grouped',
                              key_field='key', value_field='value')


def test_table_requires_same_record_columns():
    rows = [{'name': 'a', 'id': 1}, {'name': 'b', 'status': 'running'}]
    with pytest.raises(ValueError, match='consistent record fields'):
        render_result_payload(_payload(rows), view='data', shape='table')
    # Serialization never hides or projects the mismatched fields.
    assert json.loads(render_result_payload(_payload(rows), 'json', view='data')) == rows


def test_client_presentation_contract_is_local_and_wire_is_compact():
    from core.protocol.result_envelope import result_wire_event
    response = StructuredCommandResult(1, [{'name': 'demo'}], shape=ResultDataShape.TABLE,
                                       formats=('table', 'records', 'json'))
    wire = result_wire_event(101, 1, response.as_event(requested='records'))
    assert wire['presentation'] == {'source': 'data', 'default': 'table', 'requested': 'records'}
    assert 'formats' not in wire['presentation']


def test_python_packages_modes_have_distinct_layout_contracts():
    from client.commands.acmd.standalone import python_packages as command
    from core.commands.argument_validator import ArgumentCommandValidator
    validate = ArgumentCommandValidator().normalize
    spec = command.PYTHON_PACKAGES_SPEC
    assert command.python_packages(object(), validate(spec, {'loaded': True})).formats == (
        'lines', 'table', 'records', 'json')
    assert command.python_packages(object(), validate(spec, {'name': 'json'})).formats == (
        'flat', 'kv', 'json')
    assert command.python_packages(object(), validate(spec, {})).formats == (
        'table', 'records', 'json')


def test_server_rejects_detail_and_ambiguous_job_layouts_before_execution():
    for tail, expected in [
        ('--format numbered', 'Unsupported --format value: numbered'),
        ('--format kv', 'Unsupported --format value: kv'),
        ('--detail', 'Unknown option: --detail'),
        ('-d', 'Unknown option: -d'),
    ]:
        with pytest.raises(ValueError, match=expected):
            registry.parse_invocation('job', tail)
    assert registry.parse_invocation('job', '-f table').action == 'list'
    assert registry.parse_invocation('job', '--json').output_format == 'json'
