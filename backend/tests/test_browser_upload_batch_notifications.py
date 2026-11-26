"""Browser batch emits one durable notification, retaining per-file Transfer SSE."""
from server.application.web.transfer_api import WebTransferApi
from server.application.preferences.notification_event_projector import NotificationEventProjector
from server.web.event_bus import WebEventBus


class Transfers:
    def __init__(self, bus):
        self.event_bus = bus
        self.items = []

    def create_transfer(self, **kwargs):
        self.items.append(kwargs)
        result = {'transfer_id': f"transfer-{len(self.items)}", **kwargs}
        self.event_bus.publish('transfer_updated', result, target_tab_id=kwargs.get('tab_id', ''))
        self.event_bus.publish('file_transfer_lifecycle', {**result, 'lifecycle': 'started', 'state': 'running'},
                               target_tab_id=kwargs.get('tab_id', ''))
        return result


class Notifications:
    def __init__(self):
        self.items = []

    def add_notification(self, item):
        self.items.append(item)
        return item, True


def create_fixture():
    bus = WebEventBus()
    notifications = Notifications()
    projector = NotificationEventProjector(history_store=notifications, server=None)
    bus.set_notification_recorder(projector.record_event)
    service = Transfers(bus)
    return WebTransferApi(service), bus, notifications, service


def test_batch_100_transfers_keeps_all_sse_but_only_one_notification():
    api, bus, notifications, service = create_fixture()
    events = bus.subscribe(tab_id='tab')
    for index in range(100):
        result = api.create_browser_upload_transfer(
            client_id='client', filename=f'f-{index}.txt', total_bytes=12,
            tab_id='tab', batch_id='batch-1', batch_total=100, batch_index=index,
        )
        assert result['transfer_id']
    assert len(service.items) == 100
    assert not notifications.items
    api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1', folder_count=3)
    # A submitted batch is not complete until every Client transfer ends.
    assert not notifications.items
    for index, row in enumerate(service.items):
        bus.publish('file_transfer_lifecycle', {
            **row, 'transfer_id': f'transfer-{index+1}', 'lifecycle': 'stopped',
            'state': 'completed',
        }, target_tab_id='tab')
        if index < 99:
            assert not notifications.items
    assert len(notifications.items) == 1
    assert notifications.items[0]['title'] == 'File Upload Completed'
    assert notifications.items[0]['notification_key'] == 'file_transfer_batch_finished'
    assert notifications.items[0]['context']['completed'] == 100
    emitted = []
    while not events.empty():
        emitted.append(events.get_nowait()['event'])
    assert emitted.count('transfer_updated') == 100
    assert emitted.count('file_transfer_lifecycle') == 200
    assert emitted.count('notification_center_updated') == 1


def test_partial_batch_and_client_failure_still_get_one_summary():
    api, bus, notifications, service = create_fixture()
    for index in range(3):
        api.create_browser_upload_transfer(
            client_id='client', filename=f'f-{index}.txt', total_bytes=4,
            tab_id='tab', batch_id='batch-2', batch_total=100, batch_index=index,
        )
    api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-2',
                                      error='Stopped on upload failure')
    for index, row in enumerate(service.items):
        bus.publish('file_transfer_lifecycle', {
            **row, 'transfer_id': f'transfer-{index+1}', 'lifecycle': 'error' if index == 1 else 'stopped',
            'state': 'failed' if index == 1 else 'completed',
        }, target_tab_id='tab')
    assert len(notifications.items) == 1
    assert notifications.items[0]['title'] == 'File Upload Incomplete'
    assert notifications.items[0]['notification_key'] == 'file_transfer_batch_finished'
    assert notifications.items[0]['context']['completed'] == 2
    assert notifications.items[0]['context']['failed'] == 98


def test_single_file_keeps_standard_lifecycle_notification():
    api, bus, notifications, service = create_fixture()
    api.create_browser_upload_transfer(client_id='client', filename='one.txt', total_bytes=5, tab_id='tab')
    assert len(service.items) == 1
    assert notifications.items[0]['notification_key'] == 'file_transfer_started'


def test_batch_notification_delivery_is_enabled_by_default():
    from server.application.preferences.notification_preference_store import DEFAULT_NOTIFICATION_PREFERENCES
    assert DEFAULT_NOTIFICATION_PREFERENCES['events']['file_transfer_batch_finished'] is True
    assert DEFAULT_NOTIFICATION_PREFERENCES['events']['file_transfer_stopped'] is False


def test_real_sqlite_transfer_lifecycle_aggregates_after_client_completion(tmp_path):
    from server.application.transfers.transfer_service import TransferService
    from server.persistence.rch_database import RchDatabase
    database = RchDatabase(str(tmp_path / 'transfer-batch.db'))
    try:
        bus = WebEventBus()
        notifications = Notifications()
        bus.set_notification_recorder(NotificationEventProjector(history_store=notifications, server=None).record_event)
        service = TransferService(bus, database)
        api = WebTransferApi(service)
        tab_events = bus.subscribe(tab_id='test-tab')
        transfers = [api.create_browser_upload_transfer(
            client_id='client', filename=f'doc-{i}.txt', total_bytes=5,
            tab_id='test-tab', batch_id='batch-real', batch_total=12, batch_index=i,
        ) for i in range(12)]
        for item in transfers[:6]:
            service.complete_transfer(item['transfer_id'])
        api.finalize_browser_upload_batch(client_id='client', tab_id='test-tab', batch_id='batch-real')
        assert notifications.items == []
        for item in transfers[6:]:
            service.complete_transfer(item['transfer_id'])
        assert len(notifications.items) == 1
        assert notifications.items[0]['context']['completed'] == 12
        events = []
        while not tab_events.empty():
            events.append(tab_events.get_nowait())
        assert sum(e['event'] == 'transfer_updated' for e in events) == 24
        assert sum(e['event'] == 'file_transfer_lifecycle' for e in events) == 24
        assert sum(e['event'] == 'notification_center_updated' for e in events) == 1
        assert len(service.list_transfers()['recent']) == 12
    finally:
        database.close_thread_connection()
