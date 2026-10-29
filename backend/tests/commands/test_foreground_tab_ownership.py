"""Foreground snapshots preserve the existing Web Task tab ownership for race-free notices."""
from types import SimpleNamespace

from server.application.tasks.task_service import WebTaskService
from server.connection.runtime.foreground_task_snapshot import build_foreground_task_snapshot
from server.connection.runtime.session_execution_runtime import SessionExecutionRuntime


def test_foreground_task_snapshots_include_submitter_tab_id():
    runtime = SessionExecutionRuntime()
    runtime.acquire_foreground_task('command', 'shell sleep 5', source='web',
                                    task_id='task-1', tab_id='tab-A', web_task=True)
    session = SimpleNamespace(get_foreground_task=runtime.get_foreground_task,
                              session_info=SimpleNamespace(command_manifest=[]))
    snapshot = build_foreground_task_snapshot(session)
    assert snapshot['tab_id'] == 'tab-A'
    assert snapshot['command'] == 'shell sleep 5'
    runtime.release_foreground_task(task_id='task-1')
    assert build_foreground_task_snapshot(session) == {'state': 'Idle'}


def test_web_task_context_forwards_existing_tab_id_to_slot():
    forwarded = []
    session = SimpleNamespace(acquire_foreground_task=lambda **kwargs: forwarded.append(kwargs))
    context = SimpleNamespace(session=session, task_type='command', command='shell sleep 5',
                              source='web', task_id='task-1', history_entry_id='', tab_id='tab-A')
    WebTaskService._acquire_task(None, context)
    assert forwarded[0]['tab_id'] == 'tab-A'
    assert forwarded[0]['web_task'] is True


def test_server_cli_foreground_has_no_tab_owner():
    runtime = SessionExecutionRuntime()
    runtime.acquire_foreground_task('command', 'shell sleep 5', source='cli')
    session = SimpleNamespace(get_foreground_task=runtime.get_foreground_task,
                              session_info=SimpleNamespace(command_manifest=[]))
    assert build_foreground_task_snapshot(session)['tab_id'] == ''
