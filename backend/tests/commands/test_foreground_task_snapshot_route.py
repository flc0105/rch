"""Task snapshot stays available independently of browser task state."""
from types import SimpleNamespace

import pytest

from server.connection.runtime.foreground_task_snapshot import build_foreground_task_snapshot


@pytest.mark.parametrize('policy,source,command_id,expected', [
    ('process', 'web', 42, True),
    ('none', 'web', 42, False),
    ('cooperative', 'cli', 42, False),
    ('cooperative', 'web', None, False),
])
def test_connection_task_snapshot_cancel_availability(policy, source, command_id, expected):
    task = {
        'task_type': 'command', 'command': 'shell sleep 10', 'source': source,
        'task_id': 'abc', 'command_id': command_id,
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
