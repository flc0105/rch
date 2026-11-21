"""Native ACMD Result facts and result-scoped Server presentation selection."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.acmd.standalone.ps import ps
from client.runtime.execution.process.process_service import ProcessService
from core.protocol.message_queue import ResultChunk
from core.protocol.result_envelope import result_wire_event, build_result_wire_event
from core.utils.command_output import StructuredCommandResult, ResultDataShape
from core.utils.command_output import project_result_chunks
from server.application.command.command_planner import CommandPlanner
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.execution.command_stream_service import CommandStreamService


def _result(data, *, shape=ResultDataShape.TABLE, formats=('table', 'records', 'json'),
            source='data', message='', status=1, requested=None, **fields):
    structured = StructuredCommandResult(status=status, data=data, shape=shape,
                                         formats=formats, source=source, message=message, **fields)
    wire = result_wire_event(100, status, structured.as_event(requested=requested))
    return ResultChunk(status, wire, True, terminal_authoritative=True, event=wire)


def _show(entry):
    return next(project_result_chunks((entry,)))


@pytest.mark.parametrize('args,requested', [
    ({}, None), ({'format': 'records'}, 'records'), ({'f': 'json'}, 'json'),
    ({'json': True}, 'json'), ({'format': 'kv', 'json': True}, 'json'),
    ({'format': 'table', 'json': 'false'}, 'table'),
    ({'json': 'false'}, None), ({'json': 'on'}, 'json'),
])
def test_client_parses_display_options_while_server_forwards_raw(monkeypatch, args, requested):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda *_: [
        {'pid': 7, 'ppid': 1, 'name': 'python', 'username': 'x', 'status': 'running'}])
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(ps)
    if args.get('format') == 'kv' and requested != 'json':
        return
    status, event = registry.execute({'name': 'ps', 'args': args})
    assert status == 1
    assert event['presentation'].get('requested') == requested
    assert 'formats' not in event['presentation']


def test_invalid_json_flag_rejected_by_client_before_handler():
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(ps)
    status, text = registry.execute({'name': 'ps', 'args': {'json': 'maybe'}})
    assert status == 0 and '--json' in text


def test_message_error_ignores_invalid_data_layout_selection():
    entry = _result({'msg': 'not applicable'}, shape=ResultDataShape.FLAT,
                    source='message', message='Operation rejected', status=0,
                    formats=('message', 'json'))
    shown = _show(entry)
    assert shown[0] == 0
    assert shown[1] == 'Operation rejected'
    assert shown.event is entry.event


def test_planner_preserves_real_short_business_arguments():
    planner = CommandPlanner(None, lambda plan: plan, None)
    assert planner.build_argument_command_plan('acmd ps -n python -p 5')['extra']['args'] == {
        'n': 'python', 'p': '5'}
    assert planner.build_argument_command_plan('acmd ps -f')['extra']['args'] == {'f': True}


def test_native_data_default_records_json_and_raw_history():
    data = [{'pid': 7, 'name': 'runner'}]
    entry = _result(data)
    assert entry.event['data'] == data
    assert entry.event['message'] == ''
    assert entry.event['presentation'] == {
        'source': 'data', 'default': 'table'}
    assert 'runner' in _show(entry)[1]
    assert 'pid: 7' in _show(_result(data, requested='records'))[1]
    assert json.loads(_show(_result(data, requested='json'))[1]) == data
    shown = _show(entry)
    assert shown.event is entry.event and shown.event['data'] is data
    assert CommandExecutionPipeline.build_result_event(shown).text == shown[1]
    collected = CommandStreamService.collect_envelope(iter([shown]))
    assert collected.data == data and collected.status == 'success'


def test_client_rejects_unsupported_result_layout_with_english_message(monkeypatch):
    called = []
    def list_processes(*args, **kwargs):
        called.append(True)
        return [{'pid': 4, 'ppid': 1, 'name': 'test', 'username': 'x', 'status': 'running'}]
    monkeypatch.setattr(ProcessService, 'list_processes', list_processes)
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(ps)
    status, event = registry.execute({'name': 'ps', 'args': {'format': 'kv'}})
    assert status == 0
    assert event['status'] == 'error'
    assert event['message'] == 'Unsupported format for this result: kv. Available: table, records, json.'
    assert event['data'][0]['pid'] == 4
    assert event['presentation'] == {'source': 'data', 'default': 'table', 'requested': 'kv'}
    assert called == [True]  # Result-specific compatibility is checked after read-only execution.
    wire = result_wire_event(123, status, event)
    assert wire['data'] == event['data']
    assert wire['status'] == 'error'
    shown = _show(ResultChunk(status, wire, True, terminal_authoritative=True, event=wire))
    assert shown[1] == event['message']  # Terminal displays only the error, not data.
    assert shown.event is wire
    from core.utils.command_output import project_result_output_texts
    assert project_result_output_texts([wire]) == [event['message']]
    collected = CommandStreamService.collect_envelope(iter([shown]))
    assert collected.status == 'error' and collected.text == event['message']
    assert collected.data == event['data']


def test_error_results_do_not_generate_format_not_supported_warning():
    wire = result_wire_event(9, 0, 'No process found for pid 99')
    entry = ResultChunk(0, wire, True, terminal_authoritative=True, event=wire)
    shown = _show(entry)
    assert shown is entry
    assert wire['status'] == 'error'
    assert 'presentation' not in wire


def test_mode_specific_result_declares_own_formats_without_server_guessing():
    loaded = _result([{'module': 'a'}], shape=ResultDataShape.LINES,
                     formats=('lines', 'table', 'records', 'json'), line_field='module')
    detail = _result({'module': 'a', 'found': True}, shape=ResultDataShape.FLAT,
                     formats=('flat', 'kv', 'json'))
    assert _show(loaded)[1] == 'a'
    assert _show(detail)[1].startswith('module')
    assert json.loads(_show(_result({'module': 'a', 'found': True}, shape=ResultDataShape.FLAT,
                                     formats=('flat', 'kv', 'json'), requested='json'))[1])['found'] is True


def test_message_result_may_offer_explicit_json_data():
    entry = _result({'ok': True}, shape=ResultDataShape.FLAT,
                    source='message', message='Operation completed',
                    formats=('message', 'flat', 'kv', 'json'))
    assert _show(entry)[1] == 'Operation completed'
    assert json.loads(_show(_result({'ok': True}, shape=ResultDataShape.FLAT, source='message',
                                    message='Operation completed', formats=('message', 'flat', 'kv', 'json'), requested='json'))[1]) == {'ok': True}
    assert 'ok = True' in _show(_result({'ok': True}, shape=ResultDataShape.FLAT,
                                       source='message', formats=('message', 'flat', 'kv', 'json'), requested='kv'))[1]
    assert entry.event['message'] == 'Operation completed'


def test_empty_rows_message_only_applies_to_text_layout():
    entry = _result([], shape=ResultDataShape.LINES, line_field='module',
                    formats=('lines', 'table', 'records', 'json'),
                    message='No matching loaded third-party modules')
    assert _show(entry)[1] == 'No matching loaded third-party modules'
    assert json.loads(_show(_result([], shape=ResultDataShape.LINES, formats=('lines', 'json'), requested='json'))[1]) == []


def test_boolean_text_mapping_does_not_modify_raw_data():
    entry = _result([{'name': 'en0', 'up': True}],
                    text_values={'up': {'True': 'yes', 'False': 'no'}})
    assert 'yes' in _show(entry)[1]
    assert entry.event['data'][0]['up'] is True
    assert json.loads(_show(_result([{'name': 'en0', 'up': True}], requested='json'))[1])[0]['up'] is True


def test_broken_presentation_rejected_on_wire():
    data = {'event_type': 'completed', 'status': 'success', 'data': [{'name': 'x'}],
            'presentation': {'source': 'data', 'default': 'not-a-layout'}}
    with pytest.raises(ValueError, match='default presentation'):
        build_result_wire_event(7, data)
    data['presentation'] = {'source': 'data', 'default': 'table', 'requested': 'bad'}
    with pytest.raises(ValueError, match='requested presentation'):
        build_result_wire_event(7, data)
    data['presentation'] = {'source': 'data', 'default': 'table', 'requested': 'json'}
    assert build_result_wire_event(7, data)['presentation']['requested'] == 'json'


def test_client_registry_validates_business_and_display_arguments(monkeypatch):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda *_: [
        {'pid': 101, 'ppid': 1, 'name': 'python', 'username': 'x', 'status': 'running'}])
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(ps)
    ok, event = registry.execute({'name': 'ps', 'args': {'pid': '101', 'f': 'records'}})
    assert ok == 1 and event['data'][0]['pid'] == 101
    assert event['presentation']['requested'] == 'records'
    assert 'formats' not in event['presentation']
    assert registry.execute({'name': 'ps', 'args': {'pid': 'wrong'}})[0] == 0
    assert registry.execute({'name': 'ps', 'args': {'format': 'json'}})[0] == 1
    assert registry.execute({'name': 'ps', 'args': {'format': 'banana'}})[0] == 0
    assert registry.execute({'name': 'ps', 'args': {'format': 'table', 'f': 'json'}})[0] == 0


def test_shell_json_remains_plain_text_message():
    wire = result_wire_event(22, 1, '[{"name":"x"}]')
    assert wire['message'] == '[{"name":"x"}]'
    assert 'data' not in wire and 'presentation' not in wire


def test_server_executor_projects_results_without_command_kind_checks():
    # Avoid importing optional web dependencies in the focused command unit test.
    import importlib.util
    import sys
    import types
    from pathlib import Path
    fake = types.ModuleType('server.application.command.builtin_command_handler')
    fake.BuiltinCommandHandler = object
    spec = importlib.util.spec_from_file_location(
        '_isolated_result_executor',
        Path(__file__).parents[1] / 'server/application/command/executor.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'server.application.command.builtin_command_handler': fake}):
        spec.loader.exec_module(module)
    CommandExecutor = module.CommandExecutor
    entry = _result([{'pid': 42, 'name': 'demo'}], requested='records')
    seen = []
    class Remote:
        def stream_command(self, *args, **kwargs):
            seen.append(kwargs['command_type'])
            return iter([entry])
    executor = CommandExecutor.__new__(CommandExecutor)
    executor.conn = object()
    executor.server = SimpleNamespace(command_adapter=SimpleNamespace(describe_plan=lambda *a: None))
    executor.current_history_entry_id = ''
    executor.use_foreground_guard = False
    executor.remote_execution_service = Remote()
    shown = next(executor._execute_remote_plan({
        'command_type': 'acmd'})())
    assert 'pid: 42' in shown[1] and shown.event is entry.event
    other = next(executor._execute_remote_plan({'command_type': 'command'})())
    assert 'pid: 42' in other[1] and other.event is entry.event
    assert seen == ['acmd', 'command']

@pytest.mark.parametrize('flags,expected_key,expected_value', [
    ('--format records', 'format', 'records'), ('-f=json', 'f', 'json'),
    ('--json', 'json', True), ('--json=false', 'json', 'false'),
])
def test_server_forwards_display_flags_unchanged(flags, expected_key, expected_value):
    command = 'acmd ps --name "hello world" ' + flags
    plan = CommandPlanner(None, lambda item: item, None).build_argument_command_plan(command)
    assert plan['command'] == plan['extra']['raw'] == command
    assert plan['extra']['args']['name'] == 'hello world'
    assert plan['extra']['args'][expected_key] == expected_value
    assert 'presentation_format' not in plan


def test_no_display_rewrite_or_special_parser():
    planner = CommandPlanner(None, lambda plan: plan, None)
    command = 'acmd download "name with space.txt" --dest /tmp/somewhere'
    plan = planner.build_argument_command_plan(command)
    assert plan['command'] == command and plan['extra']['raw'] == command
    text = 'acmd ps --name test --format table -- --format literal'
    plan = planner.build_argument_command_plan(text)
    assert plan['extra']['args']['_args'] == ['--format', 'literal']
    assert plan['command'] == plan['extra']['raw'] == text
    assert planner.build_argument_command_plan('acmd kill --pid 1234 -9')['extra']['args']['_args'] == ['-9']


def test_ps_actions_are_raw_json_metadata_not_extra_declared_table_columns(monkeypatch):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda *_: [
        {'pid': 8, 'ppid': 1, 'name': 'demo', 'username': 'operator', 'status': 'running'}])
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(ps)
    status, event = registry.execute({'name': 'ps', 'args': {'with-actions': True}})
    assert status == 1 and event['view'] == {'actions': [{'label': 'Kill', 'command': 'acmd kill --pid {pid}', 'refresh': True}]}
    assert list(event['data'][0]) == ['pid', 'ppid', 'name', 'username', 'status']
    assert 'columns' not in event['presentation']
    wire = result_wire_event(88, status, event)
    text = _show(ResultChunk(status, wire, True, terminal_authoritative=True, event=wire))[1]
    assert all(field in text for field in ('pid', 'ppid', 'name', 'username', 'status'))
    assert '_actions' not in text and 'Kill' not in text
    records = _show(_result(event['data'], requested='records'))[1]
    assert 'name: demo' in records and '_actions' not in records
    assert wire['view']['actions'][0]['refresh'] is True
    status, default_event = registry.execute({'name': 'ps', 'args': {}})
    assert status == 1 and 'view' not in default_event
    assert list(default_event['data'][0]) == ['pid', 'ppid', 'name', 'username', 'status']


def test_activity_detail_reuses_live_projection_and_keeps_raw_result_unchanged():
    from copy import deepcopy
    from core.utils.command_output import project_result_output_texts

    data = [{'pid': 42, 'name': 'worker', '_actions': [{'label': 'Inspect', 'command': 'getpid'}]}]
    entry = _result(data, requested='records')
    events = [{'event_type': 'started'}, {'event_type': 'progress', 'message': 'Started'}, entry.event]
    before = deepcopy(events)
    text = project_result_output_texts(events)
    assert text[:2] == [None, None]
    assert text[2] == _show(entry)[1]
    assert 'pid: 42' in text[2] and '_actions:' in text[2]
    assert events == before
    # Invocation text cannot change the recorded presentation selection.
    assert project_result_output_texts(events) == text
    assert json.loads(project_result_output_texts([_result(data, requested='json').event])[0]) == data


def test_activity_default_is_result_scoped():
    from core.utils.command_output import project_result_output_texts
    raw = _result([{'pid': 3}]).event
    assert 'pid' in project_result_output_texts([raw])[0]
    assert raw['presentation'] == {'source': 'data', 'default': 'table'}


def test_actual_activity_detail_api_projects_output_without_touching_result_json():
    import importlib.util
    import sys
    import types
    from pathlib import Path
    from copy import deepcopy
    fake_config = types.ModuleType('server.config.config')
    fake_config.COMMAND_HISTORY_PAGE_SIZE = 50
    fake_config.COMMAND_HISTORY_MAX_PAGE_SIZE = 100
    path = Path(__file__).parents[1] / 'server/application/history/history_view_service.py'
    spec = importlib.util.spec_from_file_location('_isolated_acmd_history_view_service', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'server.config.config': fake_config}):
        spec.loader.exec_module(module)
    wire = _result([{'pid': 12, 'name': 'worker'}], requested='records').event
    history = {'result': [wire], 'invocation': {'command': 'acmd ps --format records'},
               'recorded_at': ['2026-11-21T00:00:00+08:00'], 'references': []}
    before = deepcopy(history)
    reader = module.HistoryViewService(SimpleNamespace(
        _get_entry=lambda *_: deepcopy(history), artifact_service=None))
    item = reader.get_execution_entry('machine', 'id')
    assert item['result'] == before['result']
    assert item['recorded_at'] == before['recorded_at']
    assert item['output_texts'] == [_show(_result([{'pid': 12, 'name': 'worker'}], requested='records'))[1]]
    assert item['files'] == [] and item['file_count'] == 0

    # Message-only results retain the original detail payload and existing UI fallback.
    history['result'] = [{'event_type': 'completed', 'message': 'done', 'status': 'success'}]
    plain = reader.get_execution_entry('machine', 'id')
    assert 'output_texts' not in plain and plain['result'][0]['message'] == 'done'


def test_omitted_history_data_is_not_reinvented_as_a_renderer_error():
    from core.utils.command_output import project_result_output_texts
    wire = _result([{'pid': 11}]).event
    wire = dict(wire)
    wire.pop('data')  # History size policy omitted the field; on-wire event stays untouched.
    assert project_result_output_texts([wire]) == [None]


def test_kill_force_uses_numeric_alias_and_f_is_always_format(monkeypatch):
    from client.commands.acmd.standalone.kill import kill, KILL_ARGUMENT_SPEC
    from client.runtime.execution.process import approved_process_service as process_module
    from core.commands.argument_validator import ArgumentCommandValidator

    planner = CommandPlanner(None, lambda plan: plan, None)
    payload = planner.build_argument_command_plan('acmd kill --pid 424242 -9 --no-confirm')
    assert payload['command'] == payload['extra']['raw']
    assert payload['extra']['args']['_args'] == ['-9']
    assert ArgumentCommandValidator().normalize(KILL_ARGUMENT_SPEC, payload['extra']['args'])['force'] is True
    assert '-9|--force' in ArgumentCommandRegistry(SimpleNamespace(command_platform='mac')).help_builder.build(KILL_ARGUMENT_SPEC)

    seen = []
    monkeypatch.setattr(process_module, 'find_targets', lambda *_args, **_kwargs: [
        {'pid': 424242, 'name': 'fake-safe-process'}])
    monkeypatch.setattr(process_module, 'terminate_verified',
                        lambda row, *, force, port=None: seen.append((row['pid'], force)) or 'SIGKILL')
    context = SimpleNamespace(command_platform='mac', _set_timeout=lambda *_: None,
                              _checkpoint=lambda **_: None)
    registry = ArgumentCommandRegistry(context)
    registry.register(kill)
    status, message = registry.execute(payload['extra'])
    assert status == 1 and 'SIGKILL sent to PID 424242' in message
    assert seen == [(424242, True)]  # Fake target only; no process was signalled.
    command = planner.build_argument_command_plan('acmd kill --pid 424242 -f json --no-confirm')
    assert command['extra']['args']['f'] == 'json'
    seen.clear()
    status, message = registry.execute(command['extra'])
    assert status == 1 and 'SIGKILL sent' in message  # Mock's fixed return label
    assert seen == [(424242, False)]  # -f json did not request SIGKILL.


def test_format_name_validation_precedes_business_handler(monkeypatch):
    called = []
    monkeypatch.setattr(ProcessService, 'list_processes', lambda *_: called.append(True) or [])
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(ps)
    status, message = registry.execute({'name': 'ps', 'args': {'f': 'banana'}})
    assert status == 0 and 'Unsupported --format value: banana' in message
    assert called == []


def test_python_packages_modes_use_result_local_format_capabilities():
    from client.commands.acmd.standalone.python_packages import python_packages
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(python_packages)
    status, event = registry.execute({'name': 'python_packages',
                                      'args': {'import': 'json', 'format': 'flat'}})
    assert status == 1 and event['presentation']['default'] == 'flat'
    assert event['presentation']['requested'] == 'flat'
    assert 'formats' not in event['presentation']
    status, event = registry.execute({'name': 'python_packages',
                                      'args': {'import': 'json', 'f': 'records'}})
    assert status == 0 and event['status'] == 'error'
    assert event['message'] == 'Unsupported format for this result: records. Available: flat, kv, json.'
    assert event['data']['module'] == 'json'
    assert event['presentation'] == {'source': 'data', 'default': 'flat',
                                     'requested': 'records', 'width': 24}
    # A format-name error is still a plain parameter-validation error, before execution.
    status, text = registry.execute({'name': 'python_packages',
                                     'args': {'import': 'json', 'f': 'ddfdd'}})
    assert status == 0 and isinstance(text, str)
    assert text.startswith('Unsupported --format value: ddfdd; supported: ')



def test_history_write_keeps_data_on_result_scoped_format_error(tmp_path):
    import importlib.util
    import sys
    import threading
    import types
    from pathlib import Path

    from client.commands.acmd.standalone.python_packages import python_packages
    from server.persistence.rch_database import RchDatabase

    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(python_packages)
    status, result = registry.execute({'name': 'python_packages',
                                       'args': {'import': 'json', 'f': 'table'}})
    wire = result_wire_event(102, status, result)

    # Load the real history writer without the optional Flask/Werkzeug Server bootstrap.
    config = types.ModuleType('server.config.config')
    config.COMMAND_HISTORY_MAX_RESULT_FIELD_BYTES = 256 * 1024
    path = Path(__file__).parents[1] / 'server/application/history/history_write_service.py'
    spec = importlib.util.spec_from_file_location('_isolated_acmd_history_writer', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'server.config.config': config}):
        spec.loader.exec_module(module)

    db = RchDatabase(str(tmp_path / 'rch.db'))
    with db.transaction() as conn:
        conn.execute('''CREATE TABLE activity_records (
            machine_id TEXT, activity_id TEXT, status TEXT,
            result_json TEXT, result_message_bytes INTEGER, result_data_bytes INTEGER,
            result_omitted INTEGER, result_summary TEXT)''')
        conn.execute('INSERT INTO activity_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                     ('machine', 'entry', 'running', '{"result": []}', 0, 0, 0, ''))
    store = SimpleNamespace(
        database=db, _lock=threading.RLock(),
        _get_machine_id_from_conn=lambda conn: 'machine',
        _now_iso=lambda: '2026-11-21T00:00:00+08:00',
    )
    module.HistoryWriteService(store).append_client_result(
        SimpleNamespace(), 'entry', wire)
    row = db.connection().execute('SELECT * FROM activity_records').fetchone()
    saved = json.loads(row['result_json'])['result'][0]
    assert saved == wire
    assert saved['status'] == 'error'
    assert saved['data']['module'] == 'json'
    assert saved['presentation']['requested'] == 'table'
    assert row['result_summary'] == wire['message']
    assert row['result_data_bytes'] > 0 and row['result_omitted'] == 0
    db.close_thread_connection()


def test_error_message_ignores_valid_display_selection(monkeypatch):
    monkeypatch.setattr(ProcessService, 'list_processes', lambda *_: [])
    registry = ArgumentCommandRegistry(SimpleNamespace(command_platform='mac'))
    registry.register(ps)
    status, message = registry.execute({'name': 'ps', 'args': {'pid': '424242', 'f': 'json'}})
    assert status == 0 and isinstance(message, str)
    assert 'No process' in message or 'No matching' in message


def test_negative_pid_is_positional_value_and_numeric_force_remains_declared_alias():
    from core.commands.argument_validator import ArgumentCommandValidator
    from client.commands.acmd.standalone.ps import PS_ARGUMENT_SPEC
    from client.commands.acmd.standalone.kill import KILL_ARGUMENT_SPEC

    planner = CommandPlanner(None, lambda item: item, None)
    validator = ArgumentCommandValidator()
    for command in ('acmd ps -1', 'acmd ps --pid -1'):
        args = planner.build_argument_command_plan(command)['extra']['args']
        assert validator.normalize(PS_ARGUMENT_SPEC, args)['pid'] == -1
    args = planner.build_argument_command_plan('acmd kill --pid 1234 -9')['extra']['args']
    assert validator.normalize(KILL_ARGUMENT_SPEC, args)['force'] is True

