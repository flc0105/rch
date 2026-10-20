"""Regression coverage for repeat cancel, terminal ACK and Server builtin disconnect."""
from types import SimpleNamespace

from client.commands.runtime.executor import CommandExecutor
from client.connection.message_router import ClientInboundMessageRouter
from server.connection.runtime.session_execution_runtime import SessionExecutionRuntime


def test_repeated_cancel_request_does_not_downgrade_stopped_or_completed():
    for terminal in ('accepted', 'stopped', 'completed'):
        runtime = SessionExecutionRuntime()
        runtime.acquire_foreground_task('command', 'read python3', task_id='t')
        runtime.bind_foreground_command_id(17)
        runtime.request_foreground_task_cancel('t')
        runtime.record_cancel_ack(17, terminal)
        repeated = runtime.request_foreground_task_cancel('t')
        assert repeated['cancel_state'] == terminal
        assert runtime.get_foreground_task()['cancel_state'] == terminal
        runtime.record_cancel_ack(17, 'accepted')
        assert runtime.get_foreground_task()['cancel_state'] == terminal


def _client_cancel_case(mode):
    sent, results = [], []
    executor = CommandExecutor(SimpleNamespace())
    ctx = executor.context_store.get_or_create(31)
    ctx.set_cancel_policy(mode)
    connection = SimpleNamespace(
        runtime=SimpleNamespace(command_executor=executor),
        send=sent.append,
        send_result=lambda *args: results.append(args),
    )
    return ClientInboundMessageRouter(connection), executor, ctx, sent, results


def test_fast_completion_during_cancel_still_delivers_terminal_ack():
    router, executor, ctx, sent, results = _client_cancel_case('process')

    def finish_before_cancel_returns():
        ctx.raise_if_cancelled()

    # A cancel handler can synchronously end the command and remove its context.
    def stop_immediately():
        try:
            finish_before_cancel_returns()
        except Exception:
            pass
        ctx.finish()
        executor.context_store.clear(31)

    ctx.add_cancel_handler(stop_immediately)
    router.handle_cancel_message({'id': 8, 'target_id': 31})
    ack_states = [entry['state'] for entry in sent]
    assert ack_states == ['stopped', 'accepted']
    assert all(entry['accepted'] for entry in sent)
    assert not results


def test_rejected_cancel_does_not_register_terminal_ack():
    router, executor, ctx, sent, results = _client_cancel_case('none')
    router.handle_cancel_message({'id': 9, 'target_id': 31})
    ctx.finish()
    assert [entry['state'] for entry in sent] == ['rejected']
    assert len(results) == 1


def test_cancel_after_context_finished_rejected_without_callback():
    router, executor, ctx, sent, results = _client_cancel_case('process')
    ctx.finish()
    router.handle_cancel_message({'id': 10, 'target_id': 31})
    assert [entry['state'] for entry in sent] == ['finished']
    assert len(results) == 1


