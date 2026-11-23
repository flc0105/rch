"""Bounded SQLite pages, machine identity filtering, and durable notification startup."""

import pytest

from server.application.transfers.transfer_service import TransferService
from server.application.preferences.notification_history_store import NotificationHistoryStore
from server.application.web.notification_history_api import WebNotificationHistoryApi
from pathlib import Path
import ast
from server.persistence.rch_database import RchDatabase


class Events:
    def publish(self, *_args, **_kwargs):
        pass


@pytest.fixture
def database(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    yield db
    db.close_thread_connection()


def test_transfers_page_from_sql_and_filter_by_machine_identity(database):
    transfers = TransferService(Events(), database)
    database.connection().execute("INSERT INTO connection_sessions(machine_id, client_id) VALUES (?, ?)", ('machine-a', 'session-1'))
    database.connection().execute("INSERT INTO connection_sessions(machine_id, client_id) VALUES (?, ?)", ('machine-a', 'session-2'))
    database.connection().execute("INSERT INTO connection_sessions(machine_id, client_id) VALUES (?, ?)", ('machine-b', 'session-3'))
    for i in range(53):
        session = ['session-1', 'session-2', 'session-3'][i % 3]
        item = transfers.create_transfer(client_id=session, direction='client_to_server', filename=f'file-{i}')
        transfers.complete_transfer(item['transfer_id'])

    first = transfers.list_transfers()
    assert first['recent_total'] == 53
    assert len(first['recent']) == 20
    second = transfers.list_transfers(offset=20)
    third = transfers.list_transfers(offset=40)
    assert len(second['recent']) == 20
    assert len(third['recent']) == 13
    assert len({v['transfer_id'] for page in (first, second, third) for v in page['recent']}) == 53

    machine_a = transfers.list_transfers(machine_id='machine-a')
    assert machine_a['recent_total'] == 36
    assert len(machine_a['recent']) == 20
    assert all(row['client_id'] in ('session-1', 'session-2') for row in machine_a['recent'])
    assert len(transfers.list_transfers(machine_id='machine-a', offset=20)['recent']) == 16
    assert transfers.list_transfers(machine_id='unknown')['recent_total'] == 0

    active = transfers.create_transfer(client_id='session-3', direction='server_to_client', filename='active')
    # Live items remain tab-scoped and unfiltered for the global activity indicator;
    # the drawer applies the machine filter to live memory while SQL filters history.
    assert [row['transfer_id'] for row in transfers.list_transfers(machine_id='machine-a')['active']] == [active['transfer_id']]
    assert [row['transfer_id'] for row in transfers.list_transfers(machine_id='machine-b')['active']] == [active['transfer_id']]


def test_notifications_have_sql_count_and_paginated_filtered_rows(database):
    store = NotificationHistoryStore(database)
    for i in range(45):
        store.add_notification({
            'id': f'notice-{i:03}', 'title': f'Event {i}',
            'type': 'error' if i % 3 == 0 else 'success',
            'shown_at': f'2026-11-23T08:{i:02}:00+00:00',
        })
    first = store.get_history()
    assert first['total_count'] == first['filtered_count'] == 45
    assert len(first['notifications']) == 20
    second = store.get_history(offset=20)
    last = store.get_history(offset=40)
    assert len(second['notifications']) == 20
    assert len(last['notifications']) == 5
    assert len({n['id'] for p in (first, second, last) for n in p['notifications']}) == 45

    errors = WebNotificationHistoryApi(store).get_history(notification_type='error')
    assert errors['total_count'] == 45
    assert errors['filtered_count'] == 15
    assert len(errors['notifications']) == 15
    assert all(n['type'] == 'error' for n in errors['notifications'])
    with pytest.raises(ValueError, match='Invalid notification type'):
        WebNotificationHistoryApi(store).get_history(notification_type='bogus')
    assert store.get_history()['total_count'] == 45


def test_notifications_not_in_startup_cleanup_and_persist_across_reopen(tmp_path):
    config_path = Path(__file__).resolve().parents[1] / 'server/config/config.py'
    node = next(n for n in ast.parse(config_path.read_text()).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SERVER_CLEANUP_ITEMS' for t in n.targets))
    assert 'notifications' not in ast.literal_eval(node.value)
    path = str(tmp_path / 'rch.db')
    database = RchDatabase(path)
    NotificationHistoryStore(database).add_notification({'id': 'durable', 'title': 'Keep me'})
    database.close_thread_connection()
    reopened = RchDatabase(path)
    assert NotificationHistoryStore(reopened).get_history()['notifications'][0]['id'] == 'durable'
    reopened.close_thread_connection()
