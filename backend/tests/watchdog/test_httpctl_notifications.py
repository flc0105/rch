"""HTTP watchdog control delivery and timeout notifications."""
import threading
import time

from server.application.connection.control_command_store import ControlCommandStore
from server.application.preferences.notification_preference_store import DEFAULT_NOTIFICATION_PREFERENCES
from server.application.preferences.notification_event_projector import NotificationEventProjector


def test_all_actions_expire_autonomously_and_only_own_commands_are_removed():
    store = ControlCommandStore()
    store.CONTROL_TIMEOUT_SECONDS = {name: 0.03 for name in store.CONTROL_TIMEOUT_SECONDS}
    signals = []
    ready = threading.Event()
    store.set_timeout_callback(lambda data: (signals.append(data), ready.set()))
    for command in ('kill', 'relaunch', 'clone'):
        store.set_pending_command('c1', command)
    assert ready.wait(1.0)
    time.sleep(.07)
    assert {item['command'] for item in signals} == {'kill', 'relaunch', 'clone'}
    assert all(item['status'] == 'timeout' for item in signals)
    assert store.pop_pending_command('c1') is None
    assert store._expiry_timers == {}
    assert store.set_pending_command('c1', 'kill')['command'] == 'kill'


def test_receive_cancels_terminal_actions_but_clone_needs_ack():
    store = ControlCommandStore()
    store.CONTROL_TIMEOUT_SECONDS = {name: 0.03 for name in store.CONTROL_TIMEOUT_SECONDS}
    signals = []
    store.set_timeout_callback(signals.append)
    kill = store.set_pending_command('one', 'kill')
    clone = store.set_pending_command('two', 'clone')
    assert store.pop_pending_command('one')['command_id'] == kill['command_id']
    assert store.pop_pending_command('two')['command_id'] == clone['command_id']
    assert store.acknowledge_control('two', clone['command_id'], 'delivered')['status'] == 'delivered'
    time.sleep(.075)
    assert signals == []
    assert store._expiry_timers == {}


def test_notification_event_projection_and_default_preferences():
    assert DEFAULT_NOTIFICATION_PREFERENCES['events']['watchdog_control_timeout'] is True
    assert DEFAULT_NOTIFICATION_PREFERENCES['events']['watchdog_control_failed'] is True
    assert DEFAULT_NOTIFICATION_PREFERENCES['events']['watchdog_control_received'] is False
    class History:
        def add_notification(self, payload):
            return payload, True
    class Server:
        def get_target_connection_by_client_id(self, _):
            raise LookupError()
    projector = NotificationEventProjector(history_store=History(), server=Server())
    example = {'client_id': 'c1', 'command': 'clone', 'command_id': '123', 'status': 'timeout'}
    expired = projector.record_event('httpctl_timeout', example, 'ev1')
    received = projector.record_event('httpctl_consumed', example, 'ev2')
    failed = projector.record_event('httpctl_result', {**example, 'status': 'failed', 'detail': 'spawn denied'}, 'ev3')
    assert expired['notification_key'] == 'watchdog_control_timeout'
    assert expired['type'] == 'error'
    assert 'clone' in expired['message']
    assert received['notification_key'] == 'watchdog_control_received'
    assert failed['notification_key'] == 'watchdog_control_failed'
    assert projector.record_event('httpctl_result', {**example, 'status': 'delivered'}, 'ev4') is None



def test_completed_outcomes_are_pruned_without_losing_new_requests():
    store = ControlCommandStore()
    old = store.set_pending_command('one', 'kill')
    store.pop_pending_command('one')
    store._outcomes_by_id[old['command_id']]['created_monotonic'] -= 360
    new = store.set_pending_command('one', 'clone')
    assert old['command_id'] not in store._outcomes_by_id
    assert new['command_id'] in store._outcomes_by_id


def test_watchdog_timeout_publishes_live_sse_and_persisted_notification(tmp_path):
    import queue
    from server.application.preferences.notification_history_store import NotificationHistoryStore
    from server.persistence.rch_database import RchDatabase
    from server.web.event_bus import WebEventBus

    database = RchDatabase(str(tmp_path / 'watchdog-notifications.db'))
    history = NotificationHistoryStore(database)
    class Server:
        def get_target_connection_by_client_id(self, _):
            raise LookupError()
    bus = WebEventBus()
    projector = NotificationEventProjector(history_store=history, server=Server())
    bus.set_notification_recorder(projector.record_event)
    listener = bus.subscribe()
    store = ControlCommandStore()
    store.CONTROL_TIMEOUT_SECONDS = {key: 0.03 for key in store.CONTROL_TIMEOUT_SECONDS}
    store.set_timeout_callback(lambda payload: bus.publish('httpctl_timeout', payload))
    try:
        store.set_pending_command('instance-1', 'clone')
        raw = listener.get(timeout=2)
        added = listener.get(timeout=2)
        assert raw['event'] == 'httpctl_timeout'
        assert added['event'] == 'notification_center_updated'
        notification = added['data']['notification']
        assert notification['notification_key'] == 'watchdog_control_timeout'
        assert notification['context']['command_id'] == raw['data']['command_id']
        assert history.get_history()['notifications'][0]['id'] == notification['id']
        with __import__('pytest').raises(queue.Empty):
            listener.get_nowait()
    finally:
        bus.unsubscribe(listener)
        database.close_thread_connection()


def test_device_event_projection_is_not_broken_by_watchdog_notifications():
    class History:
        def add_notification(self, payload):
            return payload, True
    class Server:
        def get_target_connection_by_client_id(self, _):
            raise LookupError()
    projector = NotificationEventProjector(history_store=History(), server=Server())
    item = projector.record_event('device_event', {
        'client_id': 'one', 'kind': 'custom', 'message': 'test event',
    }, 'e1')
    assert item['notification_key'] == 'device_event'
    assert item['title'] == 'Device Event'
    finished = projector.record_event('device_event', {
        'client_id': 'one', 'kind': 'command.notify.finished',
        'data': {'status': 'success', 'duration_ms': 40},
    }, 'e2')
    assert finished['title'] == 'Command Completed'
