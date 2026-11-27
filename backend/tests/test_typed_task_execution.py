"""Execution outcomes and domain-owned task submission/cancellation."""
from types import SimpleNamespace

import pytest

from core.protocol.result_envelope import ResultEvent, ResultStreamState
from server.application.command.command_execution_event import CommandExecutionEvent
from server.application.command.command_execution_pipeline import CommandExecutionPipeline
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.execution.execution_context import TaskExecutionContext
from server.application.execution.upload_execution_service import UploadExecutionService
from server.application.tasks.task_runner import WebTaskRunner
from server.application.tasks.task_service import WebTaskService, WebExecutionTaskRequest
from server.application.tasks.task_status import TaskStreamSummary
from server.application.tasks.task_store import WebTaskStore
from server.application.web.command_execution_api import WebCommandExecutionApi


def test_recovery_policy_comes_from_registry():
    requests = []
    runner = SimpleNamespace(iter_command_events=lambda _: ())
    api = WebCommandExecutionApi(SimpleNamespace(submit=requests.append),
                                 upload_task_service=None, task_runner=runner)
    for command in ('httpctl kill', 'httpctl relaunch', 'httpctl clone', 'httpctl resume',
                    'httpctl resume --client-id c --json', 'xt instance logs a --follow', 'shell echo httpctl kill'):
        api.submit_web_command('c', command)
    assert [r.use_foreground_guard for r in requests] == [False]*6 + [True]
    assert SERVER_COMMAND_REGISTRY.is_independent_input('httpctl help') is False
    assert all(r.events is runner.iter_command_events for r in requests)


def test_generic_task_does_not_need_foreground_or_transfer_for_domain_cancel():
    store = WebTaskStore()
    conn = SimpleNamespace(session_info=SimpleNamespace(client_id='c'))
    server = SimpleNamespace(get_target_connection_by_client_id=lambda _: conn,
                             activity_coordinator=SimpleNamespace(),
                             command_adapter=SimpleNamespace(prepare_command=lambda *a, **k: 'h'))
    service = WebTaskService(server, store, SimpleNamespace(run_task=lambda *a: None))
    started = []
    service._start_task_thread = lambda *a: started.append(a)
    seen = []
    def cancel(task, mark):
        seen.append(task['task_id'])
        mark()
        return {'domain_id': 'domain'}
    submitted = service.submit(WebExecutionTaskRequest('c', 'opaque label', 'example', lambda _: (),
                               use_foreground_guard=False, cancel_handler=cancel))
    task_id = submitted['task_id']
    assert started and started[0][-1] is False
    assert store.get_task(task_id).get('cancel_handler') is None
    assert service.cancel_web_task(task_id)['domain_id'] == 'domain'
    assert seen == [task_id] and store.get_task(task_id)['status'] == 'cancelling'
    assert not store.register_cancel_handler(task_id, lambda *_: None)
    store.delete_task(task_id)
    assert store.get_cancel_handler(task_id) is None


def test_upload_cancel_before_batch_binding_and_wrong_tab():
    batch = {'transfer_id': 'batch:b', 'state': 'running', 'client_id': 'c', 'tab_id': 'tab', 'cancel_supported': True}
    sent = []
    transfers = SimpleNamespace(find_active_transfer_by_task_id=lambda _: None,
        get_batch=lambda _: batch, cancel_operation=lambda *a, **k: sent.append(a))
    svc = UploadExecutionService(SimpleNamespace(get_target_connection_by_client_id=lambda _: None), None,
                                 transfer_service=transfers)
    task = {'task_id': 't', 'client_id': 'c', 'tab_id': 'tab'}
    marked = []
    assert svc.cancel_task(task, lambda: marked.append(True), transfer_id='batch:b') == {'transfer_id':'batch:b'}
    assert sent == [('batch:b',)] and marked == [True]
    with pytest.raises(ValueError):
        svc.cancel_task({**task,'tab_id':'other'}, lambda: marked.append(False), transfer_id='batch:b')
    assert marked == [True]


def test_stream_outcome_is_explicit_not_output_text():
    runner = object.__new__(WebTaskRunner)
    runner._publish_stream_chunk = lambda *a: None
    runner.task_store = SimpleNamespace(request_cancel=lambda _: None)
    ctx = TaskExecutionContext(session=None, command='test')
    for status in ('success','partial','error','cancelled','timed_out','interrupted'):
        summary = TaskStreamSummary()
        events = CommandExecutionPipeline.iter_result_events([
            ResultEvent.chunk('command cancelled, timed out'), ResultEvent.completed(status, 'done')])
        for event in events:
            runner._record_task_event(ctx, event, summary)
        assert summary.resolve_final_status() == status
    summary = TaskStreamSummary()
    runner._record_task_event(ctx, CommandExecutionEvent.chunk(0, 'command cancelled'), summary)
    assert summary.resolve_final_status() == 'interrupted'
    runner._record_task_event(ctx, CommandExecutionEvent.completed(True), summary)
    assert summary.resolve_final_status() == 'success'


def test_no_tuple_or_post_terminal_events_accepted():
    state = ResultStreamState()
    with pytest.raises(TypeError):
        state.accept((1,'text'))
    state.accept(ResultEvent.completed())
    with pytest.raises(RuntimeError, match='after completion'):
        state.accept(ResultEvent.chunk('late'))
    with pytest.raises(RuntimeError, match='Duplicate completed'):
        state.accept(ResultEvent.completed())
    missing = list(CommandExecutionPipeline.iter_result_events([ResultEvent.chunk('data')]))
    assert missing[-1].payload['result_terminal'] == 'interrupted'
