"""Task snapshot stays available independently of browser task state."""
from types import SimpleNamespace

import pytest

from server.connection.runtime.foreground_task_snapshot import build_foreground_task_snapshot


@pytest.mark.parametrize('policy,source,web_task,command_id,expected', [
    ('process', 'web', True, 42, True),
    ('process', 'quick_action', True, 42, True),
    ('process', 'web_external_tool', True, 42, True),
    ('none', 'web', True, 42, False),
    ('cooperative', 'cli', False, 42, False),
    ('cooperative', 'web_process', False, 42, False),
    ('cooperative', 'web', True, None, False),
])
def test_connection_task_snapshot_cancel_availability(policy, source, web_task, command_id, expected):
    task = {
        'task_type': 'command', 'command': 'shell sleep 10', 'source': source,
        'task_id': 'abc', 'command_id': command_id, 'web_task': web_task,
        'started_at': '2026-10-28T00:00:00+00:00',
        'cancel_state': 'running', 'cancel_requested': False,
    }
    session = SimpleNamespace(
        get_foreground_task=lambda: task,
        session_info=SimpleNamespace(command_manifest=[{'name': 'shell', 'cancel_policy': policy}]),
    )
    data = build_foreground_task_snapshot(session)
    assert data['state'] == 'Running'
    assert data['started_at'].endswith('+00:00')
    assert data['can_cancel'] is expected
    task['cancel_requested'] = True
    cancelling = build_foreground_task_snapshot(session)
    assert cancelling['state'] == 'Cancelling'
    assert cancelling['can_cancel'] is False
    session.get_foreground_task = lambda: None
    assert build_foreground_task_snapshot(session) == {'state': 'Idle'}


def test_foreground_event_broadcast_to_all_tabs_without_notification_record():
    from server.web.event_bus import WebEventBus

    bus = WebEventBus()
    notifications = []
    bus.set_notification_recorder(lambda *args, **kwargs: notifications.append(kwargs) or None)
    tab_a = bus.subscribe(tab_id='tab-a')
    tab_b = bus.subscribe(tab_id='tab-b')
    bus.publish('foreground_task_changed', {'client_id': 'client-1'})
    assert tab_a.get_nowait()['data']['client_id'] == 'client-1'
    assert tab_b.get_nowait()['data']['client_id'] == 'client-1'
    assert notifications == []


def test_foreground_task_sse_is_broadcast_from_unified_slot_for_cli_and_web():
    from server.application.connection.connection_service import WebConnectionService
    from server.web.event_bus import WebEventBus

    bus = WebEventBus()
    a, b = bus.subscribe(tab_id='a'), bus.subscribe(tab_id='b')
    handler = SimpleNamespace()
    for name in ('handle_client_opened', 'handle_client_output', 'handle_client_closed',
                 'handle_client_error', 'handle_client_frame', 'handle_client_input_error',
                 'handle_client_result', 'handle_client_snapshot', 'handle_client_update'):
        setattr(handler, name, lambda *args, **kwargs: None)
    server = SimpleNamespace(
        command_history=None, command_history_orchestrator=None,
        web_service=SimpleNamespace(
            terminal_api=SimpleNamespace(pty_session_service=handler),
            screen_view_api=SimpleNamespace(screen_view_session_service=handler),
            clipboard_api=SimpleNamespace(clipboard_session_service=handler),
            device_monitor_api=SimpleNamespace(device_monitor_session_service=handler),
            transfer_api=SimpleNamespace(transfer_service=handler),
        ),
    )
    service = WebConnectionService(server, bus, artifact_service=None)
    session = service.create_web_connection(SimpleNamespace(address=('127.0.0.1', 1000)),
                                            None, {'id': 'client-1', 'command_manifest': [
                                                {'name': 'shell', 'cancel_policy': 'process'}]})

    session.acquire_foreground_task('command', 'shell sleep 1', source='cli')
    session.runtime.bind_foreground_command_id(10)
    session.release_foreground_task(command='shell sleep 1')
    session.acquire_foreground_task('command', 'shell sleep 2', source='quick_action',
                                    task_id='web-task-2', web_task=True)
    session.runtime.bind_foreground_command_id(11)
    session.request_foreground_task_cancel('web-task-2')
    # Exercise the real incoming socket dispatcher, not just the low-level router.
    session.handle_received_message({'type': 'cancel_ack', 'target_id': 11, 'state': 'rejected'})
    session.release_foreground_task(task_id='web-task-2')

    events_a = [a.get_nowait() for _ in range(8)]
    events_b = [b.get_nowait() for _ in range(8)]
    assert events_a == events_b
    assert all(event['event'] == 'foreground_task_changed' for event in events_a)
    assert all(event['data']['client_id'] == 'client-1' for event in events_a)
    snapshots = [event['data']['task'] for event in events_a]
    assert [item['state'] for item in snapshots] == [
        'Running', 'Running', 'Idle', 'Running', 'Running', 'Cancelling', 'Running', 'Idle'
    ]
    assert not snapshots[1]['can_cancel']
    assert not snapshots[3]['can_cancel']
    assert snapshots[4]['can_cancel']
    assert snapshots[5]['cancel_state'] == 'requested'
    assert snapshots[6]['cancel_state'] == 'rejected'
    assert snapshots[6]['can_cancel']
    assert snapshots[-1] == {'state': 'Idle'}
