"""XT log follow follows the existing Server Job Logs cancellation boundary."""
import threading
import time
from types import SimpleNamespace

from server.application.tasks.task_service import WebTaskService
from test_xt_management_cli import Cli


def setup_follow():
    cli = Cli()
    commands_sent = []

    # Capture cancellation using the real ClientSession / CommandChannel API.
    cli.conn.transport.send = lambda message: (
        commands_sent.append(message['target_id']) if 'target_id' in message else None
    )
    runtime = cli.conn.runtime
    assert not hasattr(cli.conn, 'bind_foreground_command_id')
    task_id = 'web-log-follow'
    cli.conn.acquire_foreground_task(task_type='command',
        command='xt instance logs frp.frps demo --follow', task_id=task_id, web_task=True)
    client_reads = []
    first = threading.Event()
    before = cli._nested_json

    def read(command, payload):
        if command == 'external_tool_instance_logs':
            runtime.bind_foreground_command_id(len(client_reads) + 5)
            client_reads.append(payload)
            first.set()
            return {'running': True, 'content': 'FRP running\n' if len(client_reads) == 1 else '',
                    'cursor': f'cursor-{len(client_reads)}', 'reset': False}
        return before(command, payload)

    cli._nested_json = read
    return cli, runtime, task_id, first, client_reads, commands_sent


def test_server_follow_cancel_releases_foreground_slot_and_keeps_instance_running():
    cli, runtime, task_id, first, reads, cancels = setup_follow()
    result = []
    done = threading.Event()

    def run():
        try:
            result.extend(cli.xt('instance logs frp.frps demo --follow'))
        finally:
            runtime.release_foreground_task(task_id=task_id)
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert first.wait(2)
    assert result[:1] == [(1, 'FRP running\n')]
    assert runtime.get_foreground_task()['command_id'] is None
    assert not done.wait(0.05)

    service = object.__new__(WebTaskService)
    service.task_store = SimpleNamespace(request_cancel=lambda *_: {})
    service._request_task_cancel(cli.conn, task_id)
    assert done.wait(2), 'server follow did not end after cancel'
    thread.join(2)
    assert not thread.is_alive()
    assert result[-1] == (0, 'command cancelled')
    assert not cancels, 'cancel must not target an already completed log snapshot'
    assert runtime.get_foreground_task() is None
    runtime.acquire_foreground_task(task_type='command', command='pwd', task_id='next')
    assert runtime.get_foreground_task()['command'] == 'pwd'


def test_server_follow_does_not_repeat_text_without_new_cursor():
    cli, runtime, task_id, first, reads, cancels = setup_follow()
    output = []
    def run():
        output.extend(cli.xt('instance logs frp.frps demo -f'))
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert first.wait(2)
    for _ in range(100):
        if len(reads) > 1:
            break
        time.sleep(0.02)
    assert len(reads) > 1 and reads[1]['cursor'] == 'cursor-1'
    runtime.request_foreground_task_cancel(task_id)
    thread.join(2)
    assert not thread.is_alive()
    assert [text for status, text in output].count('FRP running\n') == 1
    assert output[-1] == (0, 'command cancelled')


def test_follow_cancel_during_log_rpc_is_terminal_and_slot_can_be_reused():
    cli, runtime, task_id, first, reads, cancels = setup_follow()
    entered = threading.Event()
    proceed = threading.Event()
    def slow_read(command, payload):
        if command == 'external_tool_instance_logs':
            runtime.bind_foreground_command_id(8)
            entered.set()
            assert proceed.wait(2)
            raise RuntimeError('read was cancelled')
        raise AssertionError(command)
    cli._nested_json = slow_read
    output = []
    def run():
        try:
            output.extend(cli.xt('instance logs frp.frps demo -f'))
        finally:
            runtime.release_foreground_task(task_id=task_id)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert entered.wait(2)
    service = object.__new__(WebTaskService)
    service.task_store = SimpleNamespace(request_cancel=lambda *_: {})
    service._request_task_cancel(cli.conn, task_id)
    assert cancels == [8]  # While the snapshot is genuinely in-flight, cancel targets it.
    proceed.set()
    t.join(2)
    assert not t.is_alive()
    assert output == [(0, 'command cancelled')]
    assert runtime.get_foreground_task() is None


def test_actual_web_task_runner_finalizer_releases_slot_after_follow_cancel():
    from server.application.tasks.task_runner import WebTaskRunner
    cli, runtime, task_id, first, reads, cancels = setup_follow()
    output = []
    runner = object.__new__(WebTaskRunner)
    # Keep the actual production run_command_task/finally, substitute only event plumbing.
    runner._iter_command_events = lambda _: cli.xt('instance logs frp.frps demo -f')
    runner._run_task_events = lambda _, events: output.extend(events)
    context = SimpleNamespace(task_id=task_id, command='xt instance logs frp.frps demo --follow',
        session=SimpleNamespace(release_foreground_task=runtime.release_foreground_task))
    thread = threading.Thread(target=lambda: runner.run_command_task(context), daemon=True)
    thread.start()
    assert first.wait(2)
    service = object.__new__(WebTaskService)
    service.task_store = SimpleNamespace(request_cancel=lambda *_: {})
    service._request_task_cancel(cli.conn, task_id)
    thread.join(2)
    assert not thread.is_alive()
    assert output[-1] == (0, 'command cancelled')
    assert runtime.get_foreground_task() is None


def test_client_snapshot_reader_has_no_follow_cancellation_policy():
    """Client performs only one bounded log read; the Server owns Follow cancellation."""
    import json
    from client.commands.common.mixins.external_tool_ops import CommandExternalToolMixin

    assert getattr(CommandExternalToolMixin.external_tool_instance_logs, 'command_cancel_mode', 'none') == 'none'

    class SnapshotHost(CommandExternalToolMixin):
        @property
        def external_tool_service(self):
            return SimpleNamespace(instance_log_chunk_payload=lambda payload: {
                'running': True, 'cursor': 'next', 'content': 'hello\n', 'reset': False,
            })

        def _decode_external_tool_payload(self, arg):
            return {'cursor': arg}

        def _ensure_not_cancelled(self):
            raise AssertionError('one-shot log snapshot must not depend on Client cancellation')

    status, output = SnapshotHost().external_tool_instance_logs('old')
    assert status == 1
    assert json.loads(output)['content'] == 'hello\n'
