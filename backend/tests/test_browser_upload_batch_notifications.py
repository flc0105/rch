"""Transfer batches own their durable identity; each file retains its native transfer."""

from server.application.web.transfer_api import WebTransferApi
from server.application.preferences.notification_event_projector import NotificationEventProjector
from server.application.transfers.transfer_service import TransferService
from server.persistence.rch_database import RchDatabase
from server.web.event_bus import WebEventBus


class Notifications:
    def __init__(self):
        self.items = []

    def add_notification(self, item):
        self.items.append(item)
        return item, True


def fixture(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    bus = WebEventBus()
    notifications = Notifications()
    bus.set_notification_recorder(NotificationEventProjector(
        history_store=notifications, server=None).record_event)
    service = TransferService(bus, db)
    from types import SimpleNamespace
    return db, bus, notifications, service, WebTransferApi(service, command_execution_api=SimpleNamespace(submit_web_upload_batch=lambda batch: {'task_id': batch['batch_id']}))


def begin(api, batch_id='batch-1', total=100, tab='tab'):
    return api.start_browser_upload_batch(client_id='client', batch_id=batch_id, tab_id=tab,
                                          destination_path='/remote/target', total_files=total,
                                          folder_count=3)


def member(api, i, total=100, batch_id='batch-1', tab='tab'):
    return api.create_browser_upload_transfer(client_id='client', filename=f'f-{i}.txt',
        total_bytes=12, tab_id=tab, batch_id=batch_id, batch_total=total, batch_index=i)


def test_batch_100_files_has_one_durable_parent_one_notification_and_all_child_sse(tmp_path):
    db, bus, notifications, service, api = fixture(tmp_path)
    try:
        events = bus.subscribe(tab_id='tab')
        begin(api)
        transfers = [member(api, i) for i in range(100)]
        assert service.list_transfers('tab')['active'][0]['is_batch'] is True
        assert service.list_transfers('tab')['active'][0]['total_files'] == 100
        assert len(service.list_transfers('tab')['active']) == 1
        assert len(service.list_batch_members('batch-1', tab_id='tab')) == 100
        assert not notifications.items
        for item in transfers[:50]:
            service.complete_transfer(item['transfer_id'])
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1', folder_count=3)
        assert notifications.items == []
        assert service.list_transfers('tab')['active'][0]['completed_files'] == 50
        for item in transfers[50:]:
            service.complete_transfer(item['transfer_id'])
        assert len(notifications.items) == 1
        assert notifications.items[0]['notification_key'] == 'file_transfer_batch_finished'
        assert notifications.items[0]['context']['completed'] == 100
        assert service.list_transfers('tab')['recent_total'] == 1
        assert len(service.list_transfers('tab')['recent']) == 1
        assert service.list_transfers('tab')['recent'][0]['state'] == 'completed'
        emitted = []
        while not events.empty():
            emitted.append(events.get_nowait()['event'])
        assert emitted.count('transfer_updated') == 200
        assert emitted.count('file_transfer_lifecycle') == 200
        assert emitted.count('file_transfer_batch_finished') == 1
        assert emitted.count('notification_center_updated') == 1
        db.close_thread_connection()
        reopened = RchDatabase(db.db_path)
        try:
            restored = TransferService(WebEventBus(), reopened)
            assert restored.list_transfers('new-tab')['recent_total'] == 1
            assert len(restored.list_batch_members('batch-1')) == 100
        finally:
            reopened.close_thread_connection()
    finally:
        db.close_thread_connection()


def test_partial_batch_retains_failed_children_and_one_summary(tmp_path):
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        begin(api, total=100)
        transfers = [member(api, i) for i in range(3)]
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1',
                                          error='Stopped on upload failure')
        for i, item in enumerate(transfers):
            (service.fail_transfer(item['transfer_id'], 'refused') if i == 1 else
             service.complete_transfer(item['transfer_id']))
        assert len(notifications.items) == 1
        assert notifications.items[0]['title'] == 'File Upload Incomplete'
        assert notifications.items[0]['context']['completed'] == 2
        assert notifications.items[0]['context']['failed'] == 1
        assert notifications.items[0]['context']['unsubmitted'] == 97
        batch = service.list_transfers('tab')['recent'][0]
        assert batch['is_batch'] and batch['failed_files'] == 1
        assert batch['submitted_files'] == 3
        assert batch['state'] == 'failed'
    finally:
        db.close_thread_connection()


def test_single_file_retains_independent_lifecycle_and_recent(tmp_path):
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        item = api.create_browser_upload_transfer(client_id='client', filename='one.txt',
                                                  total_bytes=5, tab_id='tab')
        assert len(notifications.items) == 1
        assert notifications.items[0]['notification_key'] == 'file_transfer_started'
        service.complete_transfer(item['transfer_id'])
        recent = service.list_transfers('tab')['recent']
        assert len(recent) == 1 and recent[0]['transfer_id'] == item['transfer_id']
        assert not recent[0].get('batch_id')
    finally:
        db.close_thread_connection()


def test_batch_recent_pagination_delete_and_empty_folders(tmp_path):
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        for index in range(25):
            key = f'b-{index}'
            begin(api, key, total=1)
            item = member(api, 0, total=1, batch_id=key)
            service.complete_transfer(item['transfer_id'])
            api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id=key)
        begin(api, 'folders-only', total=0)
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='folders-only', folder_count=3)
        assert service.list_transfers('tab')['recent_total'] == 26
        assert len(service.list_transfers('tab', limit=20)['recent']) == 20
        assert len(service.list_transfers('tab', limit=20, offset=20)['recent']) == 6
        assert len(notifications.items) == 26
        assert service.delete_recent_transfer('batch:folders-only') is True
        assert service.list_transfers('tab')['recent_total'] == 25
        assert service.clear_recent_transfers() == 25
        assert service.list_transfers('tab')['recent'] == []
        assert db.connection().execute("SELECT COUNT(*) FROM transfer_records WHERE batch_id != ''").fetchone()[0] == 0
    finally:
        db.close_thread_connection()


def test_batch_validates_owner_and_cannot_finalize_while_submission_is_open(tmp_path):
    import pytest
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        begin(api, total=2)
        with pytest.raises(ValueError, match='batch'):
            api.create_browser_upload_transfer(client_id='other', filename='f.txt', total_bytes=1,
                                               tab_id='tab', batch_id='batch-1', batch_total=2, batch_index=0)
        with pytest.raises(ValueError, match='batch'):
            member(api, 0, total=3)
        with pytest.raises(ValueError, match='batch'):
            api.finalize_browser_upload_batch(client_id='client', tab_id='other', batch_id='batch-1')
        item = member(api, 0, total=2)
        assert service.list_transfers('other')['active'] == []
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1')
        with pytest.raises(ValueError, match='batch'):
            member(api, 1, total=2)
        service.cancel_transfer(item['transfer_id'])
        assert len(notifications.items) == 1
    finally:
        db.close_thread_connection()


def test_batch_notification_delivery_enabled_by_default():
    from server.application.preferences.notification_preference_store import DEFAULT_NOTIFICATION_PREFERENCES
    assert DEFAULT_NOTIFICATION_PREFERENCES['events']['file_transfer_batch_finished'] is True
    assert DEFAULT_NOTIFICATION_PREFERENCES['events']['file_transfer_stopped'] is False


def test_batch_failed_child_exposes_real_error_and_hostname_in_sse_and_recent(tmp_path):
    db, bus, notifications, service, api = fixture(tmp_path)
    try:
        events = bus.subscribe(tab_id='tab')
        begin(api, total=2)
        first = member(api, 0, total=2)
        failed = member(api, 1, total=2)
        service.reset_progress(first['transfer_id'], hostname='MacBook-Pro', stage='transferring')
        service.reset_progress(failed['transfer_id'], hostname='MacBook-Pro', stage='transferring')
        service.complete_transfer(first['transfer_id'])
        service.fail_transfer(failed['transfer_id'], 'Permission denied: target is read-only')
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1')
        batch = service.list_transfers('tab')['recent'][0]
        assert batch['hostname'] == 'MacBook-Pro'
        assert batch['state'] == 'failed'
        assert 'f-1.txt' in batch['error']
        assert 'Permission denied' in batch['error']
        assert len(notifications.items) == 1
        assert 'Permission denied' in notifications.items[0]['message']
        published = []
        while not events.empty():
            published.append(events.get_nowait())
        finished = [item for item in published if item['event'] == 'file_transfer_batch_finished']
        assert len(finished) == 1
        assert 'Permission denied' in finished[0]['data']['error'] if isinstance(finished[0]['data'], dict) else 'Permission denied' in str(finished[0]['data'])
        db.close_thread_connection()
        restored = TransferService(WebEventBus(), RchDatabase(db.db_path))
        assert 'Permission denied' in restored.batches.get('batch-1')['error']
    finally:
        db.close_thread_connection()


def test_duplicate_index_and_auto_close_without_finalize(tmp_path):
    import pytest
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        begin(api, total=2)
        first = member(api, 0, total=2)
        with pytest.raises(ValueError, match='index'):
            member(api, 0, total=2)
        second = member(api, 1, total=2)
        service.complete_transfer(first['transfer_id'])
        service.fail_transfer(second['transfer_id'], 'Permission denied')
        batch = service.get_batch('batch-1')
        assert batch['submission_closed'] and batch['state'] == 'failed'
        assert batch['total_bytes'] is None and batch['transferred_bytes'] is None
        assert 'Permission denied' in batch['error']
        assert len(notifications.items) == 1
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1', error='generic')
        assert service.get_batch('batch-1')['error'] == batch['error']
        assert len(notifications.items) == 1
    finally:
        db.close_thread_connection()


def test_cancel_batch_rejects_other_tab_and_cleans_grants(tmp_path):
    import pytest
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        begin(api, total=3)
        first = member(api, 0, total=3)
        with pytest.raises(ValueError):
            api.cancel_transfer('batch:batch-1', tab_id='other')
        result = api.cancel_transfer('batch:batch-1', tab_id='tab')
        assert result['state'] == 'cancelled'
        assert result['cancelled_files'] == 1 and result['unsubmitted_files'] == 2
        assert api.consume_browser_upload_grant(first['transfer_id'], first['browser_upload_token']) is None
        with pytest.raises(ValueError):
            member(api, 1, total=3)
        assert len(notifications.items) == 1
    finally:
        db.close_thread_connection()


def test_disconnect_and_idle_close_incomplete_submissions(tmp_path):
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        begin(api, total=2)
        first = member(api, 0, total=2)
        service.complete_transfer(first['transfer_id'])
        api.handle_client_disconnected('client')
        assert service.get_batch('batch-1')['state'] == 'failed'
        begin(api, 'idle', total=2)
        item = member(api, 0, total=2, batch_id='idle')
        service.expire_idle_batch('idle', timeout=0)
        assert service.get_batch('idle')['state'] == 'failed'
        assert api.consume_browser_upload_grant(item['transfer_id'], item['browser_upload_token']) is None
        assert len(notifications.items) == 2
    finally:
        db.close_thread_connection()
