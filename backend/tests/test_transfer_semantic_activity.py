"""Transfer Activity persists once without recording progress/credentials or changing Quick."""
import copy
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from server.application.history.history_write_service import HistoryWriteService
from server.application.history.transfer_activity_recorder import TransferActivityRecorder
from server.application.transfers.transfer_service import TransferService
import ast
import uuid
from pathlib import Path


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:', isolation_level=None)
        self.conn.execute('CREATE TABLE activity_records (activity_id TEXT, kind TEXT, status TEXT, finished_at TEXT)')

    def connection(self):
        return self.conn

    @contextmanager
    def transaction(self):
        self.conn.execute('BEGIN')
        try:
            yield self.conn
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise
        else:
            self.conn.execute('COMMIT')


class Store:
    MAX_OUTPUT_RECORD_CHARS = 65536
    MAX_OUTPUT_RECORDS = 256

    def __init__(self):
        self.database = Database()
        self._lock = threading.RLock()
        self.entries = {}
        self.artifact_service = SimpleNamespace(get_artifact_by_id=lambda id: {
            'artifact_id': id, 'original_name': 'download.zip', 'size': 4,
        })
        self.write_service = HistoryWriteService(self)

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _get_machine_id_from_conn(conn):
        return conn.session_info.machine_id

    @staticmethod
    def _safe_text(value):
        return str(value)

    def _get_entry(self, machine_id, activity_id):
        entry = self.entries.get(activity_id)
        return copy.deepcopy(entry) if entry and entry['machine_id'] == machine_id else None

    def _insert_entry(self, entry):
        assert entry['activity_id'] not in self.entries
        self.entries[entry['activity_id']] = copy.deepcopy(entry)
        self.database.connection().execute('INSERT INTO activity_records VALUES (?,?,?,?)', (
            entry['activity_id'], entry['kind'], entry['status'], entry['finished_at']))

    def _update_entry(self, entry):
        self.entries[entry['activity_id']] = copy.deepcopy(entry)
        self.database.connection().execute('UPDATE activity_records SET status=?, finished_at=? WHERE activity_id=?', (
            entry['status'], entry['finished_at'], entry['activity_id']))


class Events:
    def publish(self, *args, **kwargs):
        pass


def setup():
    store = Store()
    transfers = TransferService(Events())
    recorder = TransferActivityRecorder(store, transfers)
    transfers.activity_recorder = recorder
    conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='machine-X', client_id='device-X'))
    return store, transfers, recorder, conn


def create(transfers, **kwargs):
    return transfers.create_transfer(client_id='device-X', direction='client_to_server', filename='a.zip',
                                     metadata={'source_count': 2}, total_bytes=42, **kwargs)['transfer_id']


def test_complete_once_with_artifact_and_no_progress_history_writes():
    store, transfers, recorder, conn = setup()
    tid = create(transfers)
    aid = recorder.track(tid, conn, action='download_files', origin='web_ui', arguments={
        'paths': ['/tmp/one', '/tmp/two'], 'count': 2, 'filename': 'a.zip', 'source': 'clipboard',
    })
    assert recorder.track(tid, conn, action='download_files', origin='web_ui', arguments={}) == aid
    assert len(store.entries) == 1
    transfers.update_progress(tid, 24)
    assert store.entries[aid]['status'] == 'running'
    assert not store.entries[aid]['result']['output_records']
    transfers.complete_transfer(tid, artifact_id='artifact-1')
    entry = store.entries[aid]
    assert entry['kind'] == 'transfer' and entry['status'] == 'success'
    assert entry['origin'] == 'web_ui'
    assert entry['files'][0]['artifact_id'] == 'artifact-1'
    assert entry['result']['output_records'][0]['text'].startswith('Transferred 2 items')
    assert entry['resolved'] == {'transfer_id': tid, 'direction': 'client_to_server'}
    transfers.update_transfer(tid, state='failed', error='too late')
    assert len(entry['result']['output_records']) == 1
    assert store.entries[aid]['status'] == 'success'


def test_browser_upload_two_phases_only_final_success_and_no_token():
    store, transfers, recorder, conn = setup()
    tid = transfers.create_transfer(client_id='device-X', direction='server_to_client', filename='b.txt',
                                    stage='uploading_to_server', total_bytes=30,
                                    metadata={'source': 'remote_file_upload'})['transfer_id']
    aid = recorder.track(tid, conn, action='upload_files', origin='web_ui', arguments={
        'filename': 'b.txt', 'count': 1, 'destination_path': '/docs',
        'browser_upload_token': 'SHOULD_NOT_PERSIST', 'staged_path': '/private/stage',
    })
    transfers.update_progress(tid, 30, stage='uploading_to_server')
    transfers.update_transfer(tid, stage='preparing')
    transfers.reset_progress(tid, stage='transferring', total_bytes=30)
    assert store.entries[aid]['status'] == 'running'
    transfers.complete_transfer(tid)
    assert store.entries[aid]['status'] == 'success'
    assert 'SHOULD_NOT_PERSIST' not in str(store.entries[aid])
    assert '/private/stage' not in str(store.entries[aid])
    assert not store.entries[aid]['files']


def test_cancel_and_disconnect_are_terminal_and_errors_remain_red_eligible():
    for state in ('cancelled', 'failed'):
        store, transfers, recorder, conn = setup()
        tid = create(transfers)
        aid = recorder.track(tid, conn, action='upload_files', origin='cli', arguments={'filename': 'a.zip'})
        if state == 'cancelled':
            transfers.cancel_transfer(tid)
        else:
            transfers.fail_active_transfers_for_client('device-X', error='offline')
        assert store.entries[aid]['status'] == ('cancelled' if state == 'cancelled' else 'error')
        assert store.entries[aid]['finished_at']


def test_recorder_reconciles_orphan_running_on_restart():
    store, transfers, recorder, conn = setup()
    tid = create(transfers)
    aid = recorder.track(tid, conn, action='download_files', origin='web_api', arguments={'filename': 'a.zip'})
    assert store.entries[aid]['status'] == 'running'
    TransferActivityRecorder(store, TransferService(Events()))
    row = store.database.connection().execute('SELECT status, finished_at FROM activity_records WHERE activity_id=?', (aid,)).fetchone()
    assert row[0] == 'interrupted' and row[1]


def test_cli_upload_claims_pending_without_discarding_quick():
    store, transfers, recorder, conn = setup()
    class FakeQuick:
        def __init__(self): self.pending = {}
        def begin(self, key, conn, command): self.pending[key] = command
        def discard(self, key): self.pending.pop(key, None)
    store.quick_store = FakeQuick()
    # Load only the orchestrator class body: full server config is unavailable
    # in this isolated test environment (Werkzeug is optional here).
    source = (Path(__file__).parents[1] / 'server/application/history/history_orchestrator.py').read_text()
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'CommandHistoryOrchestrator')
    fake_policy = SimpleNamespace(should_record_command=lambda *a, **k: True,
                                  should_record=lambda *a, **k: True,
                                  is_history_management_command=lambda c: False,
                                  is_history_replay_command=lambda c: False)
    namespace = {'threading': threading, 'uuid': uuid,
                 'CommandHistoryRecordPolicy': fake_policy, 'QuickHistoryRecordPolicy': fake_policy}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<orchestrator>', 'exec'), namespace)
    store._now_iso = lambda: datetime.now(timezone.utc).isoformat()
    orch = namespace['CommandHistoryOrchestrator'](store)
    aid = orch.begin_execution(conn, 'upload "a b.zip"', source='web', task_type='command')
    assert aid in store.quick_store.pending
    assert orch.claim_upload_intent(conn, aid) == ('web_terminal', 'upload "a b.zip"')
    assert aid in store.quick_store.pending
    tid = create(transfers)
    recorder.track(tid, conn, activity_id=aid, action='upload_files', origin='web_terminal',
                   arguments={'input': 'upload "a b.zip"', 'filename': 'a b.zip'})
    transfers.complete_transfer(tid)
    assert len(store.entries) == 1
    assert store.entries[aid]['invocation']['input'] == 'upload "a b.zip"'
    assert store.entries[aid]['status'] == 'success'


def test_cli_legacy_upload_without_tab_creates_managed_transfer(tmp_path):
    """A Server-terminal upload without browser tab ID must still be Transfer Activity."""
    from server.application.execution.upload_execution_service import UploadExecutionService

    store, transfers, recorder, conn = setup()
    local = tmp_path / 'upload.txt'
    local.write_text('remote data', encoding='utf-8')
    claims = []

    class FakeOrchestrator:
        def claim_upload_intent(self, session, entry_id):
            claims.append((session, entry_id))
            return ('cli', 'upload "upload.txt"')

    class Artifacts:
        def stage_local_file(self, path, display_name):
            assert path == str(local)
            return str(local), display_name

        def build_upload_temp_download_relative_url(self, path):
            return '/private/TOKEN-SHOULD-NOT-BE-STORED'

        def cleanup_upload_temp_file(self, path):
            pass

    class Commands:
        def get_connection(self, target):
            assert target is conn
            return conn

        def stream_command(self, session, command_text, **kw):
            assert 'receive_file' in command_text
            return iter([(1, 'Received')])

    server = SimpleNamespace(command_history_orchestrator=FakeOrchestrator())
    service = UploadExecutionService(server, Commands(), artifact_service=Artifacts(), transfer_service=transfers)
    events = list(service.iter_upload_events(
        conn, str(local), remote_path='', history_entry_id='cli-history-id',
        source='cli', build_http_receive_command=lambda data: 'receive_file ' + data['relative_url'],
        tab_id='', use_transfer_manager=False,
    ))
    assert claims == [(conn, 'cli-history-id')]
    assert len(store.entries) == 1
    entry = store.entries['cli-history-id']
    assert (entry['kind'], entry['action'], entry['origin'], entry['status']) == (
        'transfer', 'upload_files', 'cli', 'success')
    assert entry['invocation']['input'] == 'upload "upload.txt"'
    assert '/private/TOKEN' not in str(entry)
    assert any(e.event_type == 'completed' and e.ok for e in events)


def test_client_download_and_screenshot_remain_normal_command_activities():
    store, transfers, recorder, conn = setup()

    class FakeQuick:
        def __init__(self):
            self.pending = {}
        def begin(self, key, conn, command):
            self.pending[key] = command

    store.quick_store = FakeQuick()
    source = (Path(__file__).parents[1] / 'server/application/history/history_orchestrator.py').read_text()
    tree = ast.parse(source)
    entrypoints = [node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == 'CommandHistoryOrchestrator']
    fake_policy = SimpleNamespace(should_record_command=lambda *a, **k: True,
                                  should_record=lambda *a, **k: True,
                                  is_history_management_command=lambda c: False,
                                  is_history_replay_command=lambda c: False)
    namespace = {'threading': threading, 'uuid': uuid,
                 'CommandHistoryRecordPolicy': fake_policy, 'QuickHistoryRecordPolicy': fake_policy}
    exec(compile(ast.fix_missing_locations(ast.Module(body=entrypoints, type_ignores=[])), '<orchestrator>', 'exec'), namespace)
    orch = namespace['CommandHistoryOrchestrator'](store)
    aid = orch.begin_execution(conn, 'download /home/user/report.csv', source='cli', task_type='command')
    orch.describe_plan(aid, {'command_type': 'command', 'command': 'download /home/user/report.csv'})
    orch.confirm_dispatch(conn, aid, 'download /home/user/report.csv')
    entry = store.entries[aid]
    assert (entry['kind'], entry['action']) == ('command', 'invoke')
    assert entry['invocation']['input'] == 'download /home/user/report.csv'
    assert entry['resolved'] == {'command_type': 'command', 'command': 'download /home/user/report.csv'}
    assert store.quick_store.pending[aid] == 'download /home/user/report.csv'

    unrelated = orch.begin_execution(conn, 'echo download /home/user/report.csv', source='cli', task_type='command')
    orch.describe_plan(unrelated, {'command_type': 'command', 'command': 'echo download /home/user/report.csv'})
    orch.confirm_dispatch(conn, unrelated, 'echo download /home/user/report.csv')
    assert store.entries[unrelated]['kind'] == 'command'

    screenshot = orch.begin_execution(conn, 'screenshot', source='cli', task_type='command')
    orch.describe_plan(screenshot, {'command_type': 'command', 'command': 'screenshot'})
    orch.confirm_dispatch(conn, screenshot, 'screenshot')
    assert (store.entries[screenshot]['kind'], store.entries[screenshot]['action']) == ('command', 'invoke')
    assert len(store.entries) == 3
