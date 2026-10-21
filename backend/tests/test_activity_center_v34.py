"""Activity Center v34: dispatch-only records; Quick independently tracks terminal attempts."""
from types import SimpleNamespace

import pytest

from server.persistence.rch_database import RchDatabase
from server.application.history.history_store import CommandHistoryStore
from server.application.history.history_orchestrator import CommandHistoryOrchestrator


@pytest.fixture()
def setup(tmp_path):
    db = RchDatabase(str(tmp_path / 'activity.db'))
    store = CommandHistoryStore(db)
    return store, CommandHistoryOrchestrator(store), SimpleNamespace(session_info=SimpleNamespace(machine_id='m1', client_id='c1'))


def dispatch(store, orchestrator, client, command='shell pwd', *, source='web', plan=None, metadata=None):
    entry_id = orchestrator.begin_execution(client, command, source=source, metadata=metadata)
    if plan:
        orchestrator.describe_plan(entry_id, plan)
    orchestrator.confirm_dispatch(client, entry_id, (plan or {}).get('command', command),
                                  (plan or {}).get('command_type', 'command'))
    return entry_id


def test_pure_server_command_and_setup_failure_do_not_persist(setup):
    store, orch, client = setup
    pending = orch.begin_execution(client, 'rtt')
    orch.finalize_execution(client, pending, True)
    assert store.view_service.get_execution_history_page('m1')['total_count'] == 0
    pending = orch.begin_execution(client, 'script exec missing.py')
    orch.discard_execution(client, pending)
    assert store.view_service.get_execution_history_page('m1')['items'] == []


def test_real_dispatch_records_command_and_independent_quick(setup):
    store, orch, client = setup
    failed = dispatch(store, orch, client, 'shell pwd')
    orch.finalize_execution(client, failed, False)
    assert store.view_service.get_history_by_machine_id('m1')[0]['status'] == 'error'
    success = dispatch(store, orch, client, 'shell pwd')
    orch.append_output(client, success, 1, '/tmp')
    orch.finalize_execution(client, success, True)
    page = store.view_service.get_execution_history_page('m1')
    assert page['total_count'] == 2
    item = next(row for row in page['items'] if row['activity_id'] == success)
    assert set(item) == {'activity_id', 'machine_id', 'client_id', 'kind', 'action', 'origin',
                          'presentation', 'status', 'invocation', 'resolved', 'result',
                          'created_at', 'started_at', 'finished_at', 'files'}
    assert item['invocation']['input'] == 'shell pwd'
    assert item['resolved']['command'] == 'shell pwd'
    assert item['result']['output_records'][0]['text'] == '/tmp'
    assert store.view_service.get_history_by_machine_id('m1')[0]['command'] == 'shell pwd'
    assert store.view_service.get_history_by_machine_id('m1')[0]['use_count'] == 2
    assert store.view_service.get_history_by_machine_id('m1')[0]['status'] == 'success'
    assert store.view_service.get_execution_history_page('m1', errors=True)['total_count'] == 1
    assert store.view_service.get_execution_history_page('m1', kind='script')['total_count'] == 0
    assert store.view_service.get_execution_history_page('m1', kind='command')['total_count'] == 2


def test_alias_quick_action_keeps_ui_identity_and_skips_quick(setup):
    store, orch, client = setup
    activity_id = dispatch(store, orch, client, 'pyexec_collect ...', source='quick_action',
        metadata={'quick_action': True, 'quick_action_alias': 'now',
                  'quick_action_display_command': 'now', 'quick_action_presentation': 'dialog'},
        plan={'command_type': 'command', 'command': 'pyexec_collect ...'})
    orch.finalize_execution(client, activity_id, True)
    item = store.view_service.get_execution_history_page('m1')['items'][0]
    assert item['kind'] == 'alias'
    assert item['invocation']['input'] == 'now'
    assert item['invocation']['target'] == 'now'
    assert item['resolved']['command'] == 'pyexec_collect ...'
    assert item['origin'] == 'web_ui'
    assert item['presentation'] == 'dialog'
    assert store.view_service.get_history_by_machine_id('m1') == []


def test_script_does_not_copy_source_and_cancelled_terminal_is_retryable(setup):
    store, orch, client = setup
    aid = dispatch(store, orch, client, 'script exec demos/foo.py 123', source='cli',
                   plan={'command_type': 'script', 'command': 'SENSITIVE PYTHON SCRIPT'})
    orch.update_execution_status(client, aid, 'cancelling')
    orch.finalize_execution(client, aid, False, status='cancelled')
    item = store.view_service.get_execution_history_page('m1', kind='script')['items'][0]
    assert item['invocation']['target'] == 'demos/foo.py'
    assert item['invocation']['arguments'] == {'argv': ['123']}
    assert item['resolved'] == {'command_type': 'script'}
    assert item['status'] == 'cancelled'
    assert store.view_service.get_history_by_machine_id('m1')[0]['status'] == 'cancelled'
    assert store.view_service.get_history_by_machine_id('m1')[0]['command'] == 'script exec demos/foo.py 123'


def test_history_replay_retains_outer_invocation_and_uses_actual_command(setup):
    store, orch, client = setup
    aid = dispatch(store, orch, client, 'history run 3', source='cli',
                   plan={'command_type': 'command', 'command': 'shell whoami'})
    orch.finalize_execution(client, aid, True)
    assert aid
    item = store.view_service.get_execution_history_page('m1')['items'][0]
    assert item['activity_id'] == aid
    assert item['kind'] == 'command'
    assert item['invocation']['input'] == 'history run 3'
    assert item['resolved'] == {'command_type': 'command', 'command': 'shell whoami'}
    assert item['status'] == 'success'
    # Replay does not update Quick even though it creates a real Activity.
    assert store.view_service.get_history_by_machine_id('m1') == []


def test_filters_pagination_delete_does_not_touch_pin_or_quick(setup):
    store, orch, client = setup
    ids = []
    for i in range(4):
        id_ = dispatch(store, orch, client, f'shell echo {i}')
        orch.finalize_execution(client, id_, i != 2)
        ids.append(id_)
    store.write_service.set_command_pinned_by_machine_id('m1', 'shell echo 1', True)
    first = store.view_service.get_execution_history_page('m1', limit=2)
    assert len(first['items']) == 2 and first['has_more']
    second = store.view_service.get_execution_history_page('m1', limit=2, cursor=first['next_cursor'])
    assert len({x['activity_id'] for x in first['items'] + second['items']}) == 4
    assert store.view_service.get_execution_history_page('m1', errors=True)['total_count'] == 1
    assert store.write_service.delete_execution_entry_by_machine_id('m1', ids[1])
    assert any(x['command'] == 'shell echo 1' and x['is_pinned'] for x in store.view_service.get_history_by_machine_id('m1'))
    assert store.view_service.get_execution_history_page('m1')['total_count'] == 3


def test_internal_module_sources_do_not_create_activities(setup):
    store, orch, client = setup
    for source in ('web_remote_file', 'web_process', 'web_external_tool',
                   'web_runtime_config', 'web_background_job', 'web_command_autocomplete'):
        aid = orch.begin_execution(client, 'browse_dir /tmp', source=source)
        assert aid == ''
    assert store.view_service.get_execution_history_page('m1')['total_count'] == 0


def test_connection_timeline_still_exposes_command_projection(setup):
    store, orch, client = setup
    aid = dispatch(store, orch, client, 'echo value')
    orch.finalize_execution(client, aid, True)
    row = store.view_service.get_connection_command_page('m1', 'c1')['items'][0]
    assert row['summary'] == 'echo value'
    assert row['kind'] == 'command'
    assert row['activity_id'] == aid


def test_terminal_alias_resolves_with_original_invocation(setup):
    store, orch, client = setup
    aid = dispatch(store, orch, client, 'now', source='web',
                   plan={'command_type': 'command', 'alias_name': 'now',
                         'command': 'pyexec_collect import datetime'})
    orch.finalize_execution(client, aid, True)
    row = store.view_service.get_execution_history_page('m1')['items'][0]
    assert row['kind'] == 'alias'
    assert row['invocation']['input'] == 'now'
    assert row['invocation']['target'] == 'now'
    assert row['resolved']['command'] == 'pyexec_collect import datetime'
    assert store.view_service.get_history_by_machine_id('m1')[0]['command'] == 'now'


def test_real_session_send_boundary_writes_once_and_not_on_send_failure(setup):
    from server.connection.channel.session_command_channel import ClientSessionCommandChannel
    store, orch, client = setup
    sent = []

    from server.connection.runtime.session_runtime import ClientSessionRuntime
    from server.connection.services.result_dispatcher import ServerResultDispatcher
    client.context = SimpleNamespace(command_history_orchestrator=orch, script_grant_service=None)
    client.runtime = ClientSessionRuntime()
    client.send = lambda packet: (
        sent.append(packet),
        ServerResultDispatcher(client).dispatch_result(packet['id'], 1, 'ok', 1),
    )
    channel = ClientSessionCommandChannel(client)
    aid = orch.begin_execution(client, 'shell pwd', source='web')
    orch.describe_plan(aid, {'command_type': 'command', 'command': 'shell pwd'})
    assert store.view_service.get_execution_history_page('m1')['items'] == []
    assert list(channel.send_command('shell pwd', history_entry_id=aid)) == [(1, 'ok')]
    assert len(sent) == 1
    assert store.view_service.get_execution_history_page('m1')['total_count'] == 1
    orch.finalize_execution(client, aid, True)

    def broken_send(packet):
        raise ConnectionError('offline')

    client.send = broken_send
    other = orch.begin_execution(client, 'shell hostname', source='web')
    with pytest.raises(ConnectionError):
        channel.send_command('shell hostname', history_entry_id=other)
    orch.finalize_execution(client, other, False)
    assert store.view_service.get_execution_history_page('m1')['total_count'] == 1


def test_explicit_terminal_status_and_errors_filter(setup):
    store, orch, client = setup
    for status in ('cancelled', 'interrupted', 'timed_out', 'error', 'success'):
        aid = dispatch(store, orch, client, 'shell echo ' + status)
        orch.finalize_execution(client, aid, status == 'success', status=status)
    assert store.view_service.get_execution_history_page('m1', errors=True)['total_count'] == 4
    assert {x['command']: x['status'] for x in store.view_service.get_history_by_machine_id('m1')} == {
        'shell echo ' + status: status for status in ('cancelled', 'interrupted', 'timed_out', 'error', 'success')
    }
