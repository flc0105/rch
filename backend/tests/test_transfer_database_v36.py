"""Transfer Center facts survive restarts, never auto-prune, and cannot delete active transfers."""

import sqlite3

import pytest

from server.application.transfers.transfer_service import TransferService
from server.persistence.rch_database import RchDatabase


class Events:
    def __init__(self):
        self.events = []

    def publish(self, kind, payload, **kwargs):
        self.events.append((kind, dict(payload), kwargs))


@pytest.fixture
def setup(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    events = Events()
    service = TransferService(events, database)
    yield database, service, events
    database.close_thread_connection()


def make_transfer(service, *, tab_id='old-tab', filename='reports/file.txt'):
    return service.create_transfer(
        client_id='linux-1', direction='client_to_server', filename=filename,
        source_path='/srv/reports/file.txt', destination_path='/mnt/artifact/file.txt',
        hostname='Linux', total_bytes=100, tab_id=tab_id,
        metadata={'temporary_token': 'SHOULD_NOT_BE_PERSISTED'},
    )


def test_transfer_stored_at_start_progress_remains_memory_only_and_result_survives_restart(setup):
    db, transfers, _ = setup
    item = make_transfer(transfers)
    transfer_id = item['transfer_id']
    transfers.update_progress(transfer_id, 65, tab_id='old-tab', stage='transferring')
    with sqlite3.connect(db.db_path) as conn:
        record = conn.execute('SELECT state, transferred_bytes, total_bytes FROM transfer_records WHERE transfer_id=?',
                              (transfer_id,)).fetchone()
        assert record == ('running', 0, 100)
        assert 'SHOULD_NOT_BE_PERSISTED' not in '\n'.join(
            str(row) for row in conn.execute('SELECT * FROM transfer_records').fetchall())
    transfers.complete_transfer(transfer_id, artifact_id='artifact-123')
    history = TransferService(Events(), db)
    assert not history.list_transfers()['active']
    recent = history.list_transfers('brand-new-tab')['recent']
    assert len(recent) == 1
    assert recent[0]['state'] == 'completed'
    assert recent[0]['transferred_bytes'] == 100
    assert recent[0]['source_path'] == '/srv/reports/file.txt'
    assert recent[0]['completed_at']
    assert recent[0]['artifact_id'] == 'artifact-123'
    assert 'temporary_token' not in str(recent[0])
    assert history.get_transfer(transfer_id, tab_id='brand-new-tab')['artifact_id'] == 'artifact-123'


def test_no_recent_cap_and_only_manual_clear(setup):
    db, transfers, _ = setup
    for i in range(120):
        item = make_transfer(transfers, filename=f'file-{i}.txt')
        transfers.complete_transfer(item['transfer_id'])
    assert len(transfers.list_transfers()['recent']) == 120
    reloaded = TransferService(Events(), db)
    assert len(reloaded.list_transfers('another-tab')['recent']) == 120
    first = reloaded.list_transfers()['recent'][0]['transfer_id']
    assert reloaded.delete_recent_transfer(first, tab_id='different-tab') is True
    assert len(reloaded.list_transfers()['recent']) == 119
    assert reloaded.clear_recent_transfers(tab_id='different-tab') == 119
    assert reloaded.list_transfers()['recent'] == []
    assert reloaded.clear_recent_transfers() == 0


def test_restart_interrupted_and_deleting_active_forbidden(setup):
    db, transfers, _ = setup
    one = make_transfer(transfers)
    with pytest.raises(ValueError, match='active transfer'):
        transfers.delete_recent_transfer(one['transfer_id'])
    assert transfers.list_transfers()['active']
    restarted = TransferService(Events(), db)
    assert not restarted.list_transfers()['active']
    interrupted = restarted.get_transfer(one['transfer_id'])
    assert interrupted['state'] == 'interrupted'
    assert interrupted['completed_at']
    assert interrupted['error'] == 'Server restarted before transfer completed'
    assert restarted.delete_recent_transfer(one['transfer_id'])


def test_tab_scoping_active_but_history_shared(setup):
    _, transfers, _ = setup
    t1 = make_transfer(transfers, tab_id='tab-one')
    t2 = make_transfer(transfers, tab_id='tab-two')
    assert [t['transfer_id'] for t in transfers.list_transfers('tab-one')['active']] == [t1['transfer_id']]
    assert transfers.get_transfer(t2['transfer_id'], tab_id='tab-one') is None
    transfers.fail_transfer(t2['transfer_id'], 'simulated connection refused')
    assert transfers.get_transfer(t2['transfer_id'], tab_id='tab-one')['state'] == 'failed'
    assert len(transfers.list_transfers('tab-one')['recent']) == 1
    assert transfers.list_transfers('tab-one')['active'][0]['transfer_id'] == t1['transfer_id']


def test_terminal_write_failure_does_not_emit_false_completion(setup, monkeypatch):
    db, transfers, events = setup
    created = make_transfer(transfers)
    before = len(events.events)

    def fail_write(_item):
        raise sqlite3.OperationalError('database busy')

    monkeypatch.setattr(transfers.history, 'record_terminal', fail_write)
    with pytest.raises(sqlite3.OperationalError, match='database busy'):
        transfers.complete_transfer(created['transfer_id'])
    assert transfers.get_transfer(created['transfer_id'])['state'] == 'running'
    assert db.connection().execute('SELECT state FROM transfer_records WHERE transfer_id = ?',
                                   (created['transfer_id'],)).fetchone()[0] == 'running'
    assert len(events.events) == before


def test_cold_database_reopen_accepts_transfer_table_and_recovers_history(tmp_path):
    path = str(tmp_path / 'rch.db')
    db = RchDatabase(path)
    first = TransferService(Events(), db)
    completed = make_transfer(first)
    first.complete_transfer(completed['transfer_id'], artifact_id='persisted-artifact')
    pending = make_transfer(first)
    db.close_thread_connection()

    # This exercises RchDatabase's strict canonical schema check, not only the
    # Transfer store's own reinitialization on the old connection.
    reopened = RchDatabase(path)
    second = TransferService(Events(), reopened)
    assert second.get_transfer(completed['transfer_id'])['artifact_id'] == 'persisted-artifact'
    assert second.get_transfer(pending['transfer_id'])['state'] == 'interrupted'
    assert len(second.list_transfers()['recent']) == 2
    reopened.close_thread_connection()
