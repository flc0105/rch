"""Terminal outcomes, raw Result queue, and structured synchronous consumers."""
from types import SimpleNamespace

import pytest

from core.protocol.message_queue import ResultChunk
from server.application.execution.command_stream_service import CommandStreamService
from server.application.tasks.task_runner import WebTaskRunner
from server.connection.runtime.pending_results import PendingResults
from server.connection.runtime.session_runtime import ClientSessionRuntime
from rchcli.rchcli import RemoteConsole


def packet(request_id, phase, *, status=None, message=None, data=None):
    result = {'type': 'result', 'id': request_id, 'event_type': phase}
    if status is not None:
        result['status'] = status
    if message is not None:
        result['message'] = message
    if data is not None:
        result['data'] = data
    return result


def rows(*items):
    for event, legacy_status in items:
        yield ResultChunk(legacy_status, event, event['event_type'] == 'completed',
                          terminal_authoritative=True, event=event)


def test_pending_queue_is_event_native_and_rejects_duplicate_terminal():
    pending = PendingResults()
    result_queue = pending.register(13)
    progress = packet(13, 'progress', message='waiting')
    done = packet(13, 'completed', status='partial', data={'ok': 2, 'failed': 1})
    assert pending.deliver(13, progress)
    assert pending.deliver(13, done)
    assert not pending.deliver(13, packet(13, 'completed', status='success'))
    assert result_queue.get(False) is progress
    assert result_queue.get(False) is done
    assert result_queue.empty()


def test_pending_disconnect_inserts_authoritative_interrupted_completion():
    runtime = ClientSessionRuntime()
    events = runtime.pending_results.register(99)
    runtime.pending_results.deliver(99, packet(99, 'chunk', message='half'))
    runtime.pending_results.close()
    conn = SimpleNamespace(context=SimpleNamespace(), send_cancel=lambda *_: None)
    result = list(runtime.wait_for_result(conn, 99, 'test', results=events))
    assert len(result) == 2
    assert result[0].event['event_type'] == 'chunk'
    assert result[-1].event == packet(99, 'completed', status='interrupted', message='Client disconnected')
    assert result[-1][0] == 0 and result[-1].eof


@pytest.mark.parametrize('outcome,expected_numeric', [
    ('success', 1), ('partial', 1), ('error', 0),
    ('cancelled', 0), ('timed_out', 0), ('interrupted', 0),
])
def test_collector_ignores_intermediate_status_for_all_terminal_outcomes(outcome, expected_numeric):
    source = [
        (packet(12, 'chunk', message='stderr warning'), 0),
        (packet(12, 'progress', message='working'), 1),
        (packet(12, 'completed', status=outcome, message='end'), 1 if outcome == 'success' else 0),
    ]
    facts = CommandStreamService.collect_envelope(rows(*source))
    assert facts.status == outcome
    assert facts.text == 'stderr warning\nworking\nend'
    assert CommandStreamService(None).collect_result(rows(*source))[0] == expected_numeric


def test_collector_keeps_original_data_even_when_cli_projection_is_shorter():
    facts = CommandStreamService.collect_envelope([
        ResultChunk(1, 'pid: 5', True, terminal_authoritative=True,
                    event=packet(4, 'completed', status='success',
                                 data={'pid': 5, 'private_meta': 'web only'})),
    ])
    assert facts.text == 'pid: 5'
    assert CommandStreamService.json_payload(facts, command_type='control') == {
        'pid': 5, 'private_meta': 'web only',
    }


def test_text_json_is_only_parsed_for_explicit_text_commands():
    facts = CommandStreamService.collect_envelope(rows(
        (packet(12, 'completed', status='success', message='{"items": [1]}'), 1),
    ))
    assert CommandStreamService.json_payload(facts) == {'items': [1]}
    with pytest.raises(RuntimeError, match='did not return data'):
        CommandStreamService.json_payload(facts, command_type='control')


def test_invalid_structured_data_and_missing_completion_do_not_succeed():
    with pytest.raises(RuntimeError, match='expected object'):
        CommandStreamService.json_payload(CommandStreamService.collect_envelope(rows(
            (packet(7, 'completed', status='success', data=[1, 2]), 1),
        )), command_type='control')
    with pytest.raises(RuntimeError, match='without completed'):
        CommandStreamService.collect_envelope(rows(
            (packet(7, 'chunk', message='still working'), 1),
        ))
    with pytest.raises(RuntimeError, match='Duplicate completed'):
        CommandStreamService.collect_envelope(rows(
            (packet(7, 'completed', status='success'), 1),
            (packet(7, 'completed', status='error'), 0),
        ))


def test_web_task_completion_keeps_canonical_partial_status():
    runner = object.__new__(WebTaskRunner)
    published = []
    runner.event_bus = SimpleNamespace(publish=lambda *args, **kwargs: published.append((args, kwargs)))
    runner.task_store = SimpleNamespace(get_task=lambda _: {'status': 'partial'})
    runner._get_task_tab_id = lambda _: 'tab-1'
    runner._get_history_entry_id = lambda _: 'hist-1'
    runner._get_runtime_command_id = lambda _: 44
    runner._get_task_cancel_requested = lambda _: False
    context = SimpleNamespace(task_id='task-1', client_id='client-1', command='job ps', metadata={})
    runner._publish_task_complete(context)
    event_name, payload = published[0][0]
    assert event_name == 'command_complete'
    assert payload['status'] == 'partial' and payload['success'] is False
    assert payload['command_id'] == 44


@pytest.mark.parametrize('outcome,exit_code', [
    ('success', 0), ('partial', 2), ('error', 1),
    ('cancelled', 130), ('timed_out', 1), ('interrupted', 1),
])
def test_rch_cli_returns_distinct_exit_status(outcome, exit_code):
    assert RemoteConsole._result_exit_code(outcome) == exit_code
