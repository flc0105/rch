"""Transfer batches own their durable identity; each file retains its native transfer."""

from server.application.transfers.browser_upload_service import BrowserUploadService
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
    return db, bus, notifications, service, BrowserUploadService(service, upload_task_service=SimpleNamespace(submit_batch=lambda batch: {'task_id': batch['batch_id']}))


def begin(api, batch_id='batch-1', total=100, tab='tab', folders=3):
    return api.start_browser_upload_batch(client_id='client', batch_id=batch_id, tab_id=tab,
                                          destination_path='/remote/target', files=[{'relative_path': f'f-{i}.txt', 'size': 12, 'conflict_policy': 'stop'} for i in range(total)],
                                          directories=[f'folder-{i}' for i in range(folders)])


def member(api, i, total=100, batch_id='batch-1', tab='tab'):
    return api.create_browser_upload_transfer(client_id='client', filename=f'f-{i}.txt',
        total_bytes=12, destination_path='/remote/target', tab_id=tab, batch_id=batch_id, batch_total=total, batch_index=i)


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
        begin(api, total=2, folders=0)
        first = member(api, 0, total=2)
        repeated = member(api, 0, total=2)
        assert repeated['transfer_id'] == first['transfer_id']
        assert repeated['browser_upload_token'] == first['browser_upload_token']
        with pytest.raises(ValueError, match='original request'):
            api.create_browser_upload_transfer(client_id='client', filename='f-0.txt', total_bytes=13,
                destination_path='/remote/target', tab_id='tab', batch_id='batch-1', batch_total=2, batch_index=0)
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
            WebTransferApi(service, api, None).cancel_transfer('batch:batch-1', tab_id='other')
        result = WebTransferApi(service, api, None).cancel_transfer('batch:batch-1', tab_id='tab')
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
        service.fail_active_transfers_for_client('client', 'Client disconnected during file transfer')
        assert service.get_batch('batch-1')['state'] == 'failed'
        begin(api, 'idle', total=2)
        item = member(api, 0, total=2, batch_id='idle')
        service.expire_idle_batch('idle', timeout=0)
        assert service.get_batch('idle')['state'] == 'failed'
        assert api.consume_browser_upload_grant(item['transfer_id'], item['browser_upload_token']) is None
        assert len(notifications.items) == 2
    finally:
        db.close_thread_connection()


def test_batch_members_bound_to_path_name_size_and_policy(tmp_path):
    import pytest
    db, _, _, service, api = fixture(tmp_path)
    try:
        begin(api, total=1, folders=0)
        args = dict(client_id='client', filename='f-0.txt', total_bytes=12, destination_path='/remote/target',
                    tab_id='tab', batch_id='batch-1', batch_total=1, batch_index=0, conflict_policy='stop')
        for field, value in [('destination_path','/other'), ('filename','other'), ('total_bytes',13), ('conflict_policy','replace')]:
            with pytest.raises(ValueError, match='does not match'):
                api.create_browser_upload_transfer(**{**args, field: value})
        assert service.get_batch('batch-1')['submitted_files'] == 0
        api.create_browser_upload_transfer(**args)
        assert service.get_batch('batch-1')['submitted_files'] == 1
    finally:
        db.close_thread_connection()


def test_folder_plan_waits_for_confirmation_and_keeps_failure(tmp_path):
    db, _, notifications, service, api = fixture(tmp_path)
    try:
        begin(api, total=1, folders=3)
        item = member(api, 0, total=1)
        service.complete_transfer(item['transfer_id'])
        assert service.get_batch('batch-1')['state'] == 'running'
        assert not notifications.items
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1', folder_count=2, error='Folder preparation incomplete')
        batch = service.get_batch('batch-1')
        assert batch['state'] == 'failed' and batch['folder_count'] == 2
        assert 'Folder preparation incomplete' in batch['error']
        assert len(notifications.items) == 1
    finally:
        db.close_thread_connection()


def test_python_client_tree_preflight_checks_nested_conflicts_without_writes(tmp_path):
    from types import SimpleNamespace
    from client.remote_files.manager import RemoteFilesManager
    from client.runtime.filesystem.path_resolver import PathResolver
    (tmp_path / 'existing').mkdir()
    (tmp_path / 'existing' / 'a.txt').write_text('old')
    (tmp_path / 'blocked').write_text('file')
    scope = SimpleNamespace(path_resolver=PathResolver(), _checkpoint=lambda: None)
    status, data = RemoteFilesManager().inspect_upload(scope, {
        'destination_dir': str(tmp_path), 'paths': ['existing/a.txt','missing/b.txt','blocked/c.txt'],
        'directories': ['existing','missing','blocked']})
    assert status == 1
    assert [item['source'] for item in data['conflicts']] == ['existing/a.txt']
    assert [item['allowed_actions'] for item in data['folder_conflicts']] == [['stop','skip','merge'],['stop','skip']]
    assert not (tmp_path / 'missing').exists()
    status, _ = RemoteFilesManager().inspect_upload(scope, {'destination_dir':str(tmp_path),'paths':['../bad'],'directories':[]})
    assert status == 0


def test_registration_recovery_requires_identical_plan_and_owner(tmp_path):
    import pytest
    db, _, _, service, api = fixture(tmp_path)
    try:
        first = begin(api, total=2, folders=0)
        second = begin(api, total=2, folders=0)
        assert second['task_id'] == first['task_id']
        with pytest.raises(ValueError, match='mismatched'):
            begin(api, total=2, folders=0, tab='other')
        with pytest.raises(ValueError, match='plan changed'):
            begin(api, total=2, folders=1)
        item = member(api, 0, total=2)
        again = member(api, 0, total=2)
        assert again['transfer_id'] == item['transfer_id']
        assert service.get_batch('batch-1')['submitted_files'] == 1
        assert api.consume_browser_upload_grant(item['transfer_id'], item['browser_upload_token'])
        with pytest.raises(ValueError, match='already exists'):
            member(api, 0, total=2)
        api.mark_browser_upload_accepted(item['transfer_id'], tab_id='tab', task_id='task')
        assert member(api, 0, total=2)['accepted'] is True
        assert api.get_browser_upload_status(item['transfer_id'], tab_id='tab')['task_id'] == 'task'
        with pytest.raises(FileNotFoundError):
            api.get_browser_upload_status(item['transfer_id'], tab_id='other')
        with pytest.raises(FileNotFoundError):
            api.fail_browser_upload_transfer(item['transfer_id'], 'bad', tab_id='other')
        assert api.fail_browser_upload_transfer(item['transfer_id'], 'lost response', tab_id='tab')['state'] == 'running'
    finally:
        db.close_thread_connection()


def test_batch_completed_byte_counts_do_not_include_browser_intake(tmp_path):
    db, _, _, service, api = fixture(tmp_path)
    try:
        begin(api, total=2, folders=0)
        assert service.get_batch('batch-1')['planned_bytes'] == 24
        one = member(api, 0, total=2)
        api.update_browser_upload_progress(one['transfer_id'], transferred_bytes=12, tab_id='tab')
        assert service.get_batch('batch-1')['completed_bytes'] == 0
        service.complete_transfer(one['transfer_id'])
        assert service.get_batch('batch-1')['completed_bytes'] == 12
        api.finalize_browser_upload_batch(client_id='client', tab_id='tab', batch_id='batch-1', error='stopped')
        parent = service.get_batch('batch-1')
        assert parent['planned_bytes'] is None
        assert parent['submitted_bytes'] == parent['completed_bytes'] == 12
    finally:
        db.close_thread_connection()


def test_expired_unused_grant_fails_without_consuming_bytes(tmp_path, monkeypatch):
    db, _, _, service, api = fixture(tmp_path)
    try:
        from server.application.transfers import browser_upload_service as module
        monkeypatch.setattr(module.time, 'monotonic', lambda: 100)
        item = api.create_browser_upload_transfer(client_id='client', filename='a', total_bytes=1, tab_id='tab')
        monkeypatch.setattr(module.time, 'monotonic', lambda: 401)
        assert api.consume_browser_upload_grant(item['transfer_id'], item['browser_upload_token']) is None
        assert service.get_transfer(item['transfer_id'])['state'] == 'failed'
    finally:
        db.close_thread_connection()


def test_oversized_file_rejected_before_registration(tmp_path):
    import pytest
    from server.config.transfer_limits import WEB_HTTP_UPLOAD_MAX_BYTES
    db, _, _, service, api = fixture(tmp_path)
    try:
        size = WEB_HTTP_UPLOAD_MAX_BYTES + 1
        with pytest.raises(ValueError, match='size limit'):
            api.create_browser_upload_transfer(client_id='client', filename='big', total_bytes=size, tab_id='tab')
        with pytest.raises(ValueError, match='size limit'):
            api.start_browser_upload_batch(client_id='client', batch_id='big', tab_id='tab', destination_path='/remote',
                files=[{'relative_path':'big', 'size':size, 'conflict_policy':'stop'}], directories=[])
        assert service.list_transfers('tab')['active'] == []
    finally:
        db.close_thread_connection()
