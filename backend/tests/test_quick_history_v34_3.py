"""Quick History independence, retryable failures, status, exclusion and Replay."""
from types import SimpleNamespace

import pytest

from server.persistence.rch_database import RchDatabase
from server.application.history.history_store import CommandHistoryStore
from server.application.history.history_orchestrator import CommandHistoryOrchestrator
from server.application.history.quick_history import QuickHistoryRecordPolicy
from server.application.command.builtin_command_support import HistoryBuiltinSupport


@pytest.fixture()
def ctx(tmp_path):
    store = CommandHistoryStore(RchDatabase(str(tmp_path / 'quick.db')))
    client = SimpleNamespace(session_info=SimpleNamespace(machine_id='machine', client_id='client'))
    return store, CommandHistoryOrchestrator(store), client


def submit(ctx, text, status='success', *, source='web', metadata=None, task_type='', dispatch=True):
    store, orch, client = ctx
    aid = orch.begin_execution(client, text, source=source, metadata=metadata, task_type=task_type)
    if aid and dispatch:
        orch.confirm_dispatch(client, aid, text)
    orch.finalize_execution(client, aid, status == 'success', status=status)
    return aid


def quick(ctx):
    store, _, _ = ctx
    return store.view_service.get_history_by_machine_id('machine')


def test_failed_terminal_and_server_only_are_independent_of_activity(ctx):
    submit(ctx, 'shell false', 'error', dispatch=False)
    assert quick(ctx)[0]['command'] == 'shell false'
    assert quick(ctx)[0]['status'] == 'error'
    assert ctx[0].view_service.get_execution_history_page('machine')['total_count'] == 0
    submit(ctx, 'rtt', 'success', dispatch=False)
    assert {x['command'] for x in quick(ctx)} == {'shell false', 'rtt'}
    assert ctx[0].view_service.get_execution_history_page('machine')['total_count'] == 0


def test_status_overwrites_latest_attempt_and_increments_use_count(ctx):
    for status in ('error', 'success', 'timed_out', 'cancelled', 'interrupted'):
        submit(ctx, 'shell test', status)
        assert quick(ctx)[0]['status'] == status
    assert quick(ctx)[0]['use_count'] == 5
    assert len(quick(ctx)) == 1
    assert ctx[0].view_service.get_execution_history_page('machine')['total_count'] == 5


def test_replay_creates_activity_only_after_dispatch_and_never_changes_quick(ctx):
    submit(ctx, 'shell echo saved', 'error')
    store, orch, client = ctx
    before = store.view_service.get_execution_history_page('machine')['total_count']
    before_quick = quick(ctx)
    replays = ('history run 1', 'HISTORY  RUN  1', '!1', '!005')
    for number, name in enumerate(replays, 1):
        ident = orch.begin_execution(client, name, source='web')
        assert ident, name
        # Valid replay instructions are not themselves evidence of dispatch.
        assert store.view_service.get_execution_history_page('machine')['total_count'] == before + number - 1
        orch.describe_plan(ident, {'command_type': 'command', 'command': 'shell echo saved'})
        orch.confirm_dispatch(client, ident, 'shell echo saved')
        orch.finalize_execution(client, ident, True)
        record = next(row for row in store.view_service.get_execution_history_page('machine')['items']
                      if row['activity_id'] == ident)
        assert record['invocation']['input'] == name
        assert record['resolved']['command'] == 'shell echo saved'
        assert record['status'] == 'success'
        assert quick(ctx) == before_quick
    assert store.view_service.get_execution_history_page('machine')['total_count'] == before + len(replays)


def test_replay_without_client_dispatch_and_management_never_create_activity(ctx):
    store, orch, client = ctx
    for name in ('history', 'history clear', 'history clear-unsupported'):
        assert orch.begin_execution(client, name, source='web') == ''
    for name in ('history run 999', '!999'):
        ident = orch.begin_execution(client, name, source='web')
        assert ident  # candidate only; an invalid index cannot reach Client
        orch.finalize_execution(client, ident, False)
    assert quick(ctx) == []
    assert store.view_service.get_execution_history_page('machine')['total_count'] == 0


def test_clear_only_quick_then_delete_activity_without_impacting_pins(ctx):
    submit(ctx, 'shell echo pinned', 'error')
    submit(ctx, 'shell echo other', 'success')
    store, orch, client = ctx
    assert store.write_service.set_command_pinned_by_machine_id('machine', 'shell echo pinned', True)
    entries = store.view_service.get_execution_history_page('machine')['items']
    store.write_service.clear_history_for_connection(client)
    assert store.view_service.get_execution_history_page('machine')['total_count'] == 2
    rows = quick(ctx)
    assert len(rows) == 1 and rows[0]['is_pinned'] and rows[0]['command'] == 'shell echo pinned'
    assert store.write_service.delete_execution_entry_by_machine_id('machine', entries[0]['activity_id'])
    assert len(quick(ctx)) == 1
    assert store.view_service.get_execution_history_page('machine')['total_count'] == 1


def test_retry_index_resolves_quick_only_and_not_activity(ctx):
    submit(ctx, 'shell false', 'error')
    store, orch, client = ctx
    store.write_service.set_command_pinned_by_machine_id('machine', 'shell true', True)
    sent = []
    quick_builtin = HistoryBuiltinSupport(store, client, lambda: '', lambda: (lambda cmd: lambda: iter([(1, sent.append(cmd) or 'sent')])))
    assert '1  shell true' in list(quick_builtin.history(''))[0][1]
    assert list(quick_builtin.history('run 2'))[-1] == (1, 'sent')
    assert sent == ['shell false']
    assert len(quick(ctx)) == 2
    assert store.view_service.get_execution_history_page('machine')['total_count'] == 1


def test_non_terminal_sources_and_payloads_skip_quick(ctx):
    for source,metadata,task_type in (
        ('quick_action', {'quick_action': True}, ''),
        ('web', {'quick_action': True}, ''),
        ('web', {'script_run': True}, ''),
        ('web_api', {}, ''),
        ('web_remote_file', {}, 'remote_file'),
        ('web', {}, 'job_control'),
        ('web', {}, 'upload'),
    ):
        submit(ctx, 'shell echo internal', 'error', source=source, metadata=metadata, task_type=task_type)
    assert quick(ctx) == []
    assert QuickHistoryRecordPolicy.should_record('script run __json__:abc', source='web')
    assert QuickHistoryRecordPolicy.should_record('exec demo.py', source='web')
    assert QuickHistoryRecordPolicy.should_record('shell echo history run 3', source='web')


def test_discard_cleans_up_quick_intent_without_storage(ctx):
    store, orch, client = ctx
    ident = orch.begin_execution(client, 'shell echo pending', source='cli')
    orch.discard_execution(client, ident)
    orch.finalize_execution(client, ident, False)
    assert quick(ctx) == []


def test_builtin_clear_is_quick_only_and_does_not_delete_activity(ctx):
    submit(ctx, 'shell echo repeat', 'error')
    store, _, client = ctx
    builtin = HistoryBuiltinSupport(store, client, lambda: '', lambda: None)
    assert list(builtin.history('clear')) == [(1, 'Command history cleared')]
    assert quick(ctx) == []
    assert store.view_service.get_execution_history_page('machine')['total_count'] == 1


def test_quick_requires_manual_terminal_and_activity_may_be_skipped(ctx):
    store, orch, client = ctx
    assert orch.begin_execution(client, 'shell echo ignored', source='web', should_record=False) == ''
    for replay in ('!2', 'history run 3'):
        ident = orch.begin_execution(client, replay, source='cli')
        assert ident  # Activity candidate; no persist before Client dispatch
        orch.finalize_execution(client, ident, False)
    assert not QuickHistoryRecordPolicy.should_record('history clear', source='web')
    assert not QuickHistoryRecordPolicy.should_record('history', source='cli')
    assert QuickHistoryRecordPolicy.should_record('rtt', source='cli')
    assert quick(ctx) == []


def test_real_executor_replays_both_syntaxes_to_client_activity_only(ctx):
    """The history builtin must reuse the outer Activity ID for nested Client work."""
    from server.application.command.executor import CommandExecutor

    submit(ctx, 'shell echo original', 'success')
    store, orch, client = ctx
    quick_before = quick(ctx)
    dispatched = []

    class Remote:
        def stream_command(self, conn, command, *, command_type='command', extra=None,
                           history_entry_id=''):
            dispatched.append((command, command_type, history_entry_id))
            orch.confirm_dispatch(conn, history_entry_id, command, command_type)
            return iter([(1, 'sent')])

    def no_alias(name, arg, conn=None):
        raise KeyError(name)

    server = SimpleNamespace(
        alias_manager=SimpleNamespace(resolve_alias=no_alias),
        command_history=store,
        command_history_orchestrator=orch,
        web_service=SimpleNamespace(pinned_path_api=SimpleNamespace(pinned_path_store=object())),
    )
    executor = CommandExecutor(client, server, remote_execution_service=Remote())
    for outer in ('history run 1', '!1'):
        aid = orch.begin_execution(client, outer, source='cli')
        assert aid
        # The real executor rewrites !N and then invokes the nested Client plan.
        assert list(executor.process_command(outer, history_entry_id=aid)())[-1] == (1, 'sent')
        orch.finalize_execution(client, aid, True)
        record = next(item for item in store.view_service.get_execution_history_page('machine')['items']
                      if item['activity_id'] == aid)
        assert record['invocation']['input'] == outer
        assert record['resolved'] == {'command_type': 'command', 'command': 'shell echo original'}
        assert record['status'] == 'success'
        assert quick(ctx) == quick_before
    assert [command for command, _, _ in dispatched] == ['shell echo original'] * 2
    assert store.view_service.get_execution_history_page('machine')['total_count'] == 3
