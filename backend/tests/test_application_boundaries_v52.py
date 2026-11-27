"""Real request dispatch and domain-owned upload/notification lifecycle boundaries."""
import io
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.protocol.result_envelope import build_result_wire_event
from server.application.execution.command_stream_service import CommandStreamService
from server.application.preferences.notification_history_service import NotificationHistoryService
from server.application.preferences.notification_history_store import NotificationHistoryStore
from server.application.terminal.pty_session_service import PtySessionService
from server.application.transfers.browser_upload_service import BrowserUploadService
from server.application.transfers.transfer_service import TransferService
from server.application.web.terminal_api import WebTerminalApi
from server.application.web.transfer_api import WebTransferApi
from server.connection.client_session import ClientSession
from server.persistence.rch_database import RchDatabase
from server.web.event_bus import WebEventBus


@pytest.fixture
def history_components(monkeypatch):
    import server.config
    config = types.ModuleType('server.config.config')
    config.COMMAND_HISTORY_MAX_RESULT_FIELD_BYTES = 256 * 1024
    config.COMMAND_HISTORY_PAGE_SIZE = 50
    config.COMMAND_HISTORY_MAX_PAGE_SIZE = 200
    config.COMMAND_HISTORY_RECENT_LIMIT = 100
    config.RECORD_OPTIONAL_ACTIVITY = False
    monkeypatch.setitem(sys.modules, 'server.config.config', config)
    monkeypatch.setattr(server.config, 'config', config, raising=False)
    from server.application.history.activity_coordinator import ActivityCoordinator
    from server.application.history.activity_definitions import ActivityOperation
    from server.application.history.command_dispatch_adapter import CommandDispatchAdapter
    from server.application.history.history_store import CommandHistoryStore
    return CommandHistoryStore, ActivityCoordinator, CommandDispatchAdapter, ActivityOperation


@pytest.fixture
def db(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    yield database
    database.close_thread_connection()


def test_command_dispatch_association_is_connection_scoped_and_cleans_up(db, history_components):
    CommandHistoryStore, ActivityCoordinator, CommandDispatchAdapter, ActivityOperation = history_components
    store = CommandHistoryStore(db)
    coordinator = ActivityCoordinator(store)
    adapter = CommandDispatchAdapter(coordinator, lambda _: None)
    stream = CommandStreamService(SimpleNamespace(command_adapter=adapter))
    sessions = []
    for suffix in ('a', 'b'):
        transport = Mock(address=('127.0.0.1', 1))
        session = ClientSession(transport, {'machine_id': 'm', 'id': suffix})
        session.context.command_dispatch = adapter.dispatch_request
        session.acquire_foreground_task('command', 'shell echo test', task_id=suffix)
        entry = coordinator.prepare(session, ActivityOperation('command', 'invoke', {}, text='shell echo test'))
        def send(data, session=session, entry=entry, suffix=suffix):
            assert coordinator.get_bound_entry_id(session, data['id']) == entry
            assert coordinator.bind_uploaded_artifact(session, data['id'], {'artifact_id': 'artifact-' + suffix})
            # The result can arrive before send returns; pending registration already exists.
            session.runtime.pending_results.deliver(data['id'], build_result_wire_event(data['id'], {'event_type': 'chunk', 'message': suffix}))
            session.runtime.pending_results.deliver(data['id'], build_result_wire_event(data['id'], {'event_type': 'completed', 'status': 'success'}))
        transport.send.side_effect = send
        rows = stream.stream_command(session, 'shell echo test', history_entry_id=entry)
        assert session.get_foreground_task()['command_id'] == 1
        assert 'history_entry_id' not in session.get_foreground_task()
        sessions.append((session, entry, rows, suffix))
    for session, entry, rows, suffix in sessions:
        assert coordinator.get_bound_entry_id(session, 1) == entry
        assert [r.event.get('message', '') for r in rows] == [suffix, '']
        coordinator.finish(session, entry, True)
        stored = store.view_service.get_execution_entry('m', entry)
        assert stored['status'] == 'success' and stored['result'][0]['message'] == suffix
        assert any(ref['id'] == 'artifact-' + suffix for ref in stored['references'])
        assert coordinator.get_bound_entry_id(session, 1) == ''
        assert session.runtime.pending_results.get_request(1) is None


def test_send_failure_has_no_activity_or_binding(db, history_components):
    CommandHistoryStore, ActivityCoordinator, CommandDispatchAdapter, ActivityOperation = history_components
    store = CommandHistoryStore(db)
    coordinator = ActivityCoordinator(store)
    adapter = CommandDispatchAdapter(coordinator, lambda _: None)
    session = ClientSession(Mock(address=('127.0.0.1', 1)), {'machine_id': 'm', 'id': 'a'})
    session.context.command_dispatch = adapter.dispatch_request
    session.transport.send.side_effect = OSError('broken connection')
    entry = coordinator.prepare(session, ActivityOperation('command', 'invoke', {}, text='pwd'))
    with pytest.raises(OSError, match='broken connection'):
        adapter.send_command(session, 'pwd', entry_id=entry)
    assert not coordinator.get_bound_entry_id(session, 1)
    assert coordinator.pending(session, entry) is None
    assert not store.view_service.get_execution_entry('m', entry)
    assert session.runtime.pending_results.get_request(1) is None


def test_control_independent_query_does_not_bind_foreground_or_activity(db, history_components):
    CommandHistoryStore, ActivityCoordinator, CommandDispatchAdapter, ActivityOperation = history_components
    store = CommandHistoryStore(db)
    coordinator = ActivityCoordinator(store)
    adapter = CommandDispatchAdapter(coordinator, lambda _: None)
    session = ClientSession(Mock(address=('127.0.0.1', 1)), {'machine_id': 'm', 'id': 'a'})
    session.context.command_dispatch = adapter.dispatch_request
    session.acquire_foreground_task('command', 'shell sleep 30', task_id='long')
    session.runtime.bind_foreground_command_id(999)
    def send(data):
        session.runtime.pending_results.deliver(data['id'], build_result_wire_event(data['id'], {'event_type': 'completed', 'status': 'success', 'data': {}}))
    session.transport.send.side_effect = send
    from core.protocol.control import ControlDomain, ConfigurationAction
    rows = session.send_command('', type='control', domain=ControlDomain.CONFIGURATION, action=ConfigurationAction.GET, payload={})
    assert list(rows)[0].succeeded
    assert session.get_foreground_task()['command_id'] == 999
    assert coordinator.get_bound_entry_id(session, 1) == ''


class TemporaryArtifacts:
    def __init__(self, root):
        self.root = root
        self.removed = []
    def create_upload_temp_path(self, filename, *, expected_size, owner):
        path = self.root / filename
        return str(path), 'reservation'
    def cleanup_upload_temp_file(self, path):
        self.removed.append(path)
        Path(path).unlink(missing_ok=True)


def test_browser_intake_has_one_grant_and_hands_off_staged_bytes(db, tmp_path):
    transfer = TransferService(WebEventBus(), db)
    artifacts = TemporaryArtifacts(tmp_path)
    def submit(client_id, path, display_name, destination, **kwargs):
        assert client_id == 'client' and destination == '/tmp'
        assert display_name == 'good.txt' and Path(path).read_bytes() == b'hello'
        assert kwargs['tab_id'] == 'a'
        return {'task_id': 'task'}
    uploads = BrowserUploadService(transfer, upload_task_service=SimpleNamespace(submit_upload=submit), artifact_service=artifacts)
    api = WebTransferApi(transfer, uploads, None)
    registration = api.create_browser_upload_transfer(client_id='client', filename='good.txt', total_bytes=5, destination_path='/tmp', tab_id='a', operation_id='unique')
    tid, token = registration['transfer_id'], registration['browser_upload_token']
    assert registration['browser_upload_path'] == f'/api/transfers/browser-upload/{tid}/content'
    assert uploads.consume_browser_upload_grant(tid, 'wrong') is None
    grant = uploads.consume_browser_upload_grant(tid, token)
    assert grant and uploads.consume_browser_upload_grant(tid, token) is None
    assert uploads.receive_content(tid, grant, io.BytesIO(b'hello').read, content_length=5) == {'task_id': 'task'}
    assert api.get_browser_upload_status(tid, tab_id='a')['accepted']
    assert api.get_browser_upload_status(tid, tab_id='a')['task_id'] == 'task'
    assert not artifacts.removed
    (tmp_path / 'good.txt').unlink()


def test_browser_intake_short_stream_cleans_file_and_does_not_submit(db, tmp_path):
    transfer = TransferService(WebEventBus(), db)
    artifacts = TemporaryArtifacts(tmp_path)
    submit = Mock()
    uploads = BrowserUploadService(transfer, upload_task_service=SimpleNamespace(submit_upload=submit), artifact_service=artifacts)
    registration = uploads.create_browser_upload_transfer(client_id='client', filename='short.txt', total_bytes=5, tab_id='a')
    tid = registration['transfer_id']
    grant = uploads.consume_browser_upload_grant(tid, registration['browser_upload_token'])
    with pytest.raises(ValueError, match='size mismatch'):
        uploads.receive_content(tid, grant, io.BytesIO(b'abc').read)
    assert not submit.called
    assert artifacts.removed == [str(tmp_path / 'short.txt')]
    assert not (tmp_path / 'short.txt').exists()
    assert transfer.get_transfer(tid)['state'] == 'failed'


def test_notification_domain_cleanup_emits_same_pruned_event(db):
    bus = Mock()
    store = NotificationHistoryStore(db)
    service = NotificationHistoryService(store, bus)
    old, _ = store.add_notification({'title': 'old', 'shown_at': '2020-01-01T00:00:00Z'})
    candidates = service.list_cleanup_candidates()
    assert candidates == [old]
    result = service.cleanup_notifications([old['id']], expected={old['id']: old})
    assert result['removed'] == [old]
    bus.publish.assert_called_once_with('notification_center_updated', {'action': 'pruned', 'ids': [old['id']]})
    assert service.get_history()['total_count'] == 0


def test_pty_web_facade_returns_service_snapshot_only():
    session = Mock()
    service = PtySessionService(SimpleNamespace(get_target_connection_by_client_id=lambda _: session))
    opened = service.create_session('c')
    info = WebTerminalApi(service).get_pty_ws_info(opened['pty_session_id'])
    assert info == {'pty_session_id': opened['pty_session_id'], 'ws_token': opened['ws_token']}
    with pytest.raises(KeyError):
        WebTerminalApi(service).get_pty_ws_info('missing')


def test_retired_schema_is_not_created_or_auto_migrated(db):
    tables = {r[0] for r in db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'command_executions' not in tables
    # An existing retired table is not silently destroyed at application startup.
    with db.transaction() as conn:
        conn.execute('CREATE TABLE command_executions(entry_id TEXT PRIMARY KEY)')
        conn.execute("INSERT INTO command_executions VALUES ('old')")
    db.close_thread_connection()
    reopened = RchDatabase(db.db_path)
    try:
        assert reopened.fetch_one('SELECT entry_id FROM command_executions')[0] == 'old'
        assert reopened.integrity_check() == 'ok'
    finally:
        reopened.close_thread_connection()


def test_confirmation_decorator_is_client_owned(monkeypatch):
    from client.runtime.execution.command_confirmation import confirm
    from client.runtime.execution.interaction_service import CommandInteractions
    calls = []
    monkeypatch.setattr(CommandInteractions, 'confirm', lambda self, *a, **k: False)
    @confirm('Proceed?')
    def example(self, arg):
        calls.append(arg)
        return 1, arg
    owner = SimpleNamespace()
    assert example(owner, 'x')[0] == 0
    assert example(owner, '--no-confirm x') == (1, 'x')
    assert calls == ['x']


def test_browser_stream_read_exception_releases_staging_and_transfer(db, tmp_path):
    transfer = TransferService(WebEventBus(), db)
    artifacts = TemporaryArtifacts(tmp_path)
    submit = Mock()
    uploads = BrowserUploadService(transfer, upload_task_service=SimpleNamespace(submit_upload=submit), artifact_service=artifacts)
    registration = uploads.create_browser_upload_transfer(client_id='client', filename='broken.txt', total_bytes=5, tab_id='a')
    tid = registration['transfer_id']
    grant = uploads.consume_browser_upload_grant(tid, registration['browser_upload_token'])
    with pytest.raises(OSError, match='disconnected'):
        uploads.receive_content(tid, grant, Mock(side_effect=OSError('disconnected')))
    assert not submit.called
    assert artifacts.removed == [str(tmp_path / 'broken.txt')]
    assert not (tmp_path / 'broken.txt').exists()
    assert transfer.get_transfer(tid)['state'] == 'failed'
