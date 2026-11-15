"""Wrapper builtins keep nested Result facts and use only terminal status."""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.protocol.message_queue import ResultChunk
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.command.command_notify_builtin_support import CommandNotifyBuiltinSupport
from server.application.command.command_output_builtin_support import CommandOutputBuiltinSupport


def result_event(phase, status=None, message='', data=None, item_status=1, eof=None):
    event = {'type': 'result', 'id': 8, 'event_type': phase, 'message': message}
    if status is not None:
        event['status'] = status
    if data is not None:
        event['data'] = data
    return ResultChunk(item_status, event, phase == 'completed' if eof is None else eof,
                       terminal_authoritative=True, event=event)


def saveout(tmp_path, rows):
    file_path = tmp_path / 'out.txt'
    extras = []

    class Artifacts:
        def allocate_command_output_artifact_path(self, **kwargs):
            return {'file_path': str(file_path), 'machine_id': 'm', 'original_name': 'out.txt'}

        def register_command_output_artifact(self, *, extra=None, **kwargs):
            extras.append(extra)
            return {'artifact_id': 'art', 'original_name': 'out.txt', 'size': file_path.stat().st_size}

    conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m', client_id='', hostname='h'),
                           get_foreground_task=lambda: {})
    support = CommandOutputBuiltinSupport(None, conn, None, None, lambda: '', Artifacts(), None)
    support._build_inner_executor = lambda _: lambda: iter(rows)
    final = list(support.saveout('shell_stream echo test'))
    assert len(final) == 1
    assert final[0].event['event_type'] == 'completed'
    return final[0], file_path.read_text(), extras[0]


def notify(rows):
    events = []
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='c1', hostname='h'))
    support = CommandNotifyBuiltinSupport(conn, None, lambda: 'history1',
                                          SimpleNamespace(ingest=events.append))
    support._build_inner_executor = lambda _: lambda: iter(rows)
    forwarded = list(support.notify('shell_stream echo test'))
    return forwarded, events


def test_saveout_intermediate_stderr_is_not_final_failure_and_json_is_real_json(tmp_path):
    rows = [
        result_event('chunk', message='hello'),
        result_event('chunk', message='temporary warning', item_status=0),
        result_event('chunk', data={'name': 'hello', 'items': [1, 2]}),
        result_event('completed', status='success', message='Finished'),
    ]
    final, output, extra = saveout(tmp_path, rows)
    assert final[0] == 1 and final.event['status'] == 'success'
    assert output.startswith('hello\ntemporary warning\n')
    assert '"name": "hello"' in output and "'name': 'hello'" not in output
    assert output.endswith('Finished\n')
    assert extra['final_status'] == 'success'


@pytest.mark.parametrize('status', ['error', 'cancelled', 'timed_out', 'interrupted', 'partial'])
def test_saveout_propagates_final_status(tmp_path, status):
    rows = [result_event('chunk', message='work', item_status=1),
            result_event('completed', status=status, message='end', item_status=0)]
    final, _, extra = saveout(tmp_path, rows)
    assert extra['final_status'] == status
    assert final.event['status'] == status
    assert final[0] == (1 if status == 'partial' else 0)


def test_saveout_uses_existing_cli_projection_not_full_web_data(tmp_path):
    original = {'event_type': 'completed', 'status': 'success',
                'data': {'public': 'yes', 'internal_metadata': 'not printed'}}
    row = ResultChunk(1, 'public: yes', True, terminal_authoritative=True, event=original)
    final, output, extra = saveout(tmp_path, [row])
    assert final.event['status'] == 'success'
    assert output == 'public: yes\n'
    assert 'internal_metadata' not in output
    assert extra['final_status'] == 'success'


def test_saveout_incomplete_stream_is_interrupted(tmp_path):
    final, text, extra = saveout(tmp_path, [result_event('chunk', message='half finished')])
    assert final.event['status'] == 'interrupted' and final[0] == 0
    assert text == 'half finished\n' and extra['final_status'] == 'interrupted'


def test_saveout_internal_plain_tuple_result_still_supported(tmp_path):
    final, output, _ = saveout(tmp_path, [(0, 'warn'), (1, 'done')])
    assert final.event['status'] == 'success' and output == 'warn\ndone\n'


def test_notify_forwards_nested_events_unmodified_and_uses_completed_status():
    rows = [result_event('chunk', message='warning', item_status=0),
            result_event('completed', status='success', message='finished')]
    forwarded, events = notify(rows)
    assert forwarded == rows
    assert len(events) == 1 and events[0]['data']['status'] == 'success'
    assert events[0]['kind'] == 'command.notify.finished'


@pytest.mark.parametrize('status', ['error', 'cancelled', 'timed_out', 'interrupted'])
def test_notify_terminal_failure_even_when_previous_output_succeeded(status):
    rows = [result_event('chunk', message='fine', item_status=1),
            result_event('completed', status=status, message='end', item_status=0)]
    _, events = notify(rows)
    assert events[0]['data']['status'] == 'failed'


def test_notify_missing_terminal_is_not_success_and_empty_is_not_success():
    for rows in ([result_event('chunk', message='work')], []):
        _, events = notify(rows)
        assert events[0]['data']['status'] == 'failed'


def test_notify_plain_tuple_result_uses_last_status():
    _, events = notify([(0, 'warning'), (1, 'final')])
    assert events[0]['data']['status'] == 'success'


def test_notify_does_not_send_two_command_terminals():
    rows = [result_event('chunk', message='first'),
            result_event('completed', status='success', message='end')]
    forwarded, events = notify(rows)
    assert sum(bool(getattr(row, 'event', {}) and row.event['event_type'] == 'completed')
               for row in forwarded) == 1
    assert len(events) == 1  # Notification is a separate Device Event.


def test_history_and_gopin_preambles_are_intermediate_not_completed():
    # The full Server config requires optional Werkzeug; exercise the two
    # builtins in an isolated process with their genuine registration code.
    source = r'''
import sys, types
from types import SimpleNamespace as NS
config = types.ModuleType('server.config.config')
config.SCRIPT_PATH = 'backend/server/resources/scripts'
config.COMMAND_HISTORY_RECENT_LIMIT = 100
sys.modules['server.config.config'] = config
from core.protocol.message_queue import ResultChunk
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.command.builtin_command_support import HistoryBuiltinSupport, PinnedPathBuiltinSupport
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY as reg
inner = ResultChunk(1, {'type':'result','id':18,'event_type':'completed','status':'success','message':'/tmp'},
                    True, terminal_authoritative=True,
                    event={'type':'result','id':18,'event_type':'completed','status':'success','message':'/tmp'})
class Store:
 def get_history_for_connection(self,_):return [{'command':'pwd','index':1,'is_pinned':False}]
history = HistoryBuiltinSupport(Store(), NS(), lambda:'', lambda:lambda text:lambda:iter([inner]))
rows=list(history.history(reg.parse_invocation('history','run 1')))
assert rows[0][1]=='sending command: pwd'
assert rows[0].eof is False and rows[0].event['event_type']=='chunk'
assert rows[1] is inner
assert CommandExecutionPipeline.build_result_event(rows[0]).payload['intermediate_result'] is True
assert CommandExecutionPipeline.build_result_event(rows[1]).payload['result_terminal']=='success'
pinned=PinnedPathBuiltinSupport.__new__(PinnedPathBuiltinSupport)
pinned._get_machine_id=lambda:'m'
pinned.list_pinned_paths=lambda:[]
pinned.pinned_path_store=NS(get_item_by_name=lambda _id,_name:{'path':'/tmp/work'})
pinned.command_processor_factory=lambda:lambda text:lambda:iter([inner])
rows=list(pinned.gopin(reg.parse_invocation('gopin','go work')))
assert rows[0][1]=='gopin work -> cd /tmp/work'
assert rows[0].eof is False and rows[0].event['event_type']=='chunk'
assert rows[1] is inner
assert CommandExecutionPipeline.build_result_event(rows[0]).payload['intermediate_result'] is True
assert CommandExecutionPipeline.build_result_event(rows[1]).payload['result_terminal']=='success'
print('WRAPPER_PREAMBLE_OK')
'''
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, '-c', source], cwd=root,
                            env={**os.environ, 'PYTHONPATH': str(root / 'backend')},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WRAPPER_PREAMBLE_OK' in result.stdout

@pytest.mark.parametrize('status', ['success', 'partial', 'error', 'cancelled', 'timed_out', 'interrupted'])
def test_rendered_wrapper_result_keeps_canonical_terminal_status(status):
    message = 'saved to command_output: result.txt\nartifact_id: a\nsize: 12 bytes'
    envelope = {'event_type': 'completed', 'status': status, 'message': message}
    rendered = ResultChunk(1 if status in ('success', 'partial') else 0,
                           message, True, terminal_authoritative=True, event=envelope)
    output = CommandExecutionPipeline.build_result_event(rendered)
    assert output.payload['result_terminal'] == status
    assert output.payload['result_envelope'] == envelope
    assert output.text == message
    if status == 'cancelled':
        assert output.event_type == 'cancelled'
    elif status in ('error', 'timed_out', 'interrupted'):
        assert output.event_type == 'error'
    else:
        assert output.event_type == 'chunk'
