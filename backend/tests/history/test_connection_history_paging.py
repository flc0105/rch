"""History pages are bounded at SQLite, not sliced after loading snapshots."""

from server.application.connection.connection_history_store import ConnectionHistoryStore
from server.persistence.rch_database import RchDatabase


def test_connection_history_uses_bounded_sql_pages(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    conn = database.connection()
    for i in range(45):
        conn.execute(
            """INSERT INTO connection_sessions (
                machine_id, client_id, connected_at, connected_at_ms,
                disconnected_at, disconnected_at_ms, last_seen_at, duration_ms,
                termination_reason, termination_detail, snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 100, '', '{}', ?)""",
            ('machine-1', f'client-{i:02}', '2026-11-05T10:00:00', i + 1,
             '2026-11-05T10:01:00', i + 2, '2026-11-05T10:01:00',
             '{"addr":"host-%02d"}' % i),
        )

    queries = []
    conn.set_trace_callback(queries.append)
    decoded = []
    original_decode = store._row_to_session
    store._row_to_session = lambda row, **kwargs: (decoded.append(row['client_id']), original_decode(row, **kwargs))[1]
    try:
        first = store.get_history('machine-1')
        assert [r['client_id'] for r in first['sessions']] == [f'client-{i:02}' for i in range(44, 24, -1)]
        assert first['connection_count'] == 45
        assert first['has_more'] is True
        assert len(decoded) == 20

        second = store.get_history('machine-1', limit=20, offset=20)
        assert [r['client_id'] for r in second['sessions']] == [f'client-{i:02}' for i in range(24, 4, -1)]
        assert second['has_more'] is True
        assert len(decoded) == 40

        last = store.get_history('machine-1', limit=20, offset=40)
        assert [r['client_id'] for r in last['sessions']] == [f'client-{i:02}' for i in range(4, -1, -1)]
        assert last['has_more'] is False
        assert len(decoded) == 45
        assert all('addr' in row for page in (first, second, last) for row in page['sessions'])
        page_queries = [q.lower() for q in queries if 'select * from connection_sessions' in q.lower()]
        assert len(page_queries) == 3
        assert all('limit' in q and 'offset' in q for q in page_queries)
        assert 'limit 21 offset 0' in page_queries[0]
        assert 'limit 21 offset 20' in page_queries[1]
        assert 'limit 21 offset 40' in page_queries[2]
    finally:
        conn.set_trace_callback(None)
        database.close_thread_connection()


def test_client_id_search_queries_all_sessions_not_just_loaded_page(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    for index in range(45):
        store.record_connected({
            'machine_id': 'machine-search', 'client_id': f'node_{index:02}',
            'connected_at': f'2026-11-11T10:00:{index:02}+00:00',
            'os_name': 'macOS', 'os_ver': '15', 'os_type': 'not-for-history',
            'listener_id': 'L1', 'listener_name': 'Main',
            'listener_port': 8080, 'listener_protocol': 'tcp',
        })
    page = store.get_history('machine-search', client_id_search='NODE_03')
    assert [row['client_id'] for row in page['sessions']] == ['node_03']
    assert page['connection_count'] == 45  # Toolbar total remains machine-wide.
    assert not page['has_more']
    assert store.get_history('machine-search', client_id_search='node%03')['sessions'] == []
    item = page['sessions'][0]
    assert item['os_name'] == 'macOS' and item['os_ver'] == '15'
    assert {'connection_state', 'tracking_source', 'commands', 'hostname', 'os_type', 'os_alias',
            'listener_id', 'listener_port', 'python_ver', 'launch_command'}.isdisjoint(item)
    raw = database.connection().execute(
        'SELECT snapshot FROM connection_sessions WHERE machine_id = ? AND client_id = ?',
        ('machine-search', 'node_03'),
    ).fetchone()['snapshot']
    import json
    snapshot = json.loads(raw)
    assert { 'listener_id', 'listener_name', 'listener_port', 'listener_protocol',
             'os_name', 'os_ver' } <= snapshot.keys()
    assert {'os_type', 'arch', 'manufacturer', 'model', 'client_id', 'machine_id',
            'last_seen_at', 'python_execution_mode', 'http_transfer_mode'}.isdisjoint(snapshot)
    database.close_thread_connection()


def test_same_client_id_remains_one_connection_history_row(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    connection = {'machine_id': 'm', 'client_id': 'c', 'connected_at': '2026-11-11T10:00:00+00:00'}
    store.record_connected(connection)
    store.record_disconnected({**connection, 'disconnected_at': '2026-11-11T10:01:00+00:00'},
                              termination_reason='client_exit')
    store.record_connected({**connection, 'connected_at': '2026-11-11T10:02:00+00:00'})
    page = store.get_history('m')
    assert page['connection_count'] == 1
    assert page['sessions'][0]['client_id'] == 'c'
    assert page['sessions'][0]['connected_at'] == connection['connected_at']
    assert page['sessions'][0]['disconnected_at'] == ''
    assert page['sessions'][0]['termination_reason'] == ''
    database.close_thread_connection()


def test_connection_history_service_returns_explicit_activity_counts(tmp_path):
    from types import SimpleNamespace
    from server.application.connection.connection_service import WebConnectionService

    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(db)
    store.record_connected({'machine_id': 'm', 'client_id': 'c', 'connected_at': '2026-11-11T01:00:00+00:00'})

    class ActivityView:
        def get_connection_command_counts_by_machine_id(self, machine_id, client_ids):
            assert machine_id == 'm' and client_ids == ['c']
            return {'c': 4}

        def get_connection_command_totals(self, machine_id):
            assert machine_id == 'm'
            return {'total': 5, 'unassigned': 1}

    server = SimpleNamespace(
        connections=SimpleNamespace(all=lambda: []),
        command_history=SimpleNamespace(view_service=ActivityView()),
    )
    service = WebConnectionService(server, None, None, connection_history_store=store)
    result = service.get_machine_connection_history('m', client_id_search='c')
    assert result['activity_count'] == 5
    assert result['unassigned_activity_count'] == 1
    assert result['sessions'][0]['activity_count'] == 4
    assert not {'command_count', 'unassigned_command_count', 'tracking_started_at', 'next_offset', 'schema_version'} & result.keys()
    assert not {'commands', 'command_count', 'connection_state', 'schema_version'} & result['sessions'][0].keys()
    db.close_thread_connection()


def test_server_filters_before_pagination_and_dropdown_options_cover_all_history(tmp_path):
    """Two matching rows in a 103-row machine do not imply another filtered page."""
    import json

    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    conn = database.connection()
    for index in range(103):
        special = index in (3, 6)  # Outside the latest 20 rows.
        values = {
            'integrity': 'High' if special else ('Medium' if index % 2 else ''),
            'launch_mode': 'IDE' if special else 'terminal',
            'launch_source': 'pycharm' if index == 3 else 'vscode',
        }
        conn.execute(
            '''INSERT INTO connection_sessions(
                machine_id, client_id, connected_at, connected_at_ms,
                disconnected_at, disconnected_at_ms, last_seen_at, duration_ms,
                termination_reason, termination_detail, snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            ('M', f'node_{index:03}', '2026-11-11T00:00:00+00:00', index,
             '2026-11-11T00:01:00+00:00', index + 1, '2026-11-11T00:01:00+00:00', 60000,
             'timeout' if special else ('client_exit' if index % 2 else ''), '{}', json.dumps(values)),
        )
    result = store.get_history('M', integrity='HIGH', launch_mode='ide', termination_reason='TIMEOUT')
    assert [row['client_id'] for row in result['sessions']] == ['node_006', 'node_003']
    assert not result['has_more']
    assert result['connection_count'] == 103
    assert result['filter_options']['integrity'] == ['high', 'medium', 'unknown']
    assert result['filter_options']['launch_mode'] == ['ide', 'terminal']
    assert 'timeout' in result['filter_options']['termination_reason']
    assert 'unknown' not in result['filter_options']['termination_reason']
    assert not store.get_history('M', client_id_search='node_06', integrity='high')['sessions']
    assert [row['client_id'] for row in store.get_history('M', client_id_search='NODE_00', integrity='high')['sessions']] == ['node_006', 'node_003']
    assert not store.get_history('M', integrity='unknown', termination_reason='unknown')['sessions']
    assert store.get_history('M', integrity="x' OR 1=1 --")['sessions'] == []
    database.close_thread_connection()


def test_server_filtered_pages_have_true_has_more_until_last_match(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    for i in range(55):
        store.record_connected({
            'machine_id': 'M', 'client_id': f'n{i:03}',
            'connected_at': f'2026-11-11T10:00:{i:02}+00:00',
            'integrity': 'High' if i % 2 == 0 else 'Low',
            'launch_mode': 'terminal',
        })
    first = store.get_history('M', integrity='high')
    assert len(first['sessions']) == 20
    assert first['has_more'] is True
    second = store.get_history('M', integrity='high', offset=20)
    assert len(second['sessions']) == 8
    assert second['has_more'] is False
    assert not store.get_history('M', integrity='high', offset=28)['sessions']
    database.close_thread_connection()


def test_connection_service_preserves_machine_totals_when_search_and_filters_are_combined(tmp_path):
    from types import SimpleNamespace
    from server.application.connection.connection_service import WebConnectionService

    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    for client_id, integrity, mode, reason in [
        ('node_A', 'High', 'IDE', 'timeout'),
        ('node_B', 'Low', 'terminal', 'client_exit'),
        ('other_C', 'High', 'IDE', 'timeout'),
    ]:
        item = {'machine_id': 'machine-test', 'client_id': client_id,
                'connected_at': '2026-11-11T10:00:00+00:00',
                'integrity': integrity, 'launch_mode': mode}
        store.record_connected(item)
        store.record_disconnected({**item, 'disconnected_at': '2026-11-11T10:01:00+00:00'},
                                  termination_reason=reason)

    class ActivityView:
        def get_connection_command_counts_by_machine_id(self, machine_id, client_ids):
            assert machine_id == 'machine-test'
            assert client_ids == ['node_A']
            return {'node_A': 2}

        def get_connection_command_totals(self, machine_id):
            return {'total': 25, 'unassigned': 3}

    server = SimpleNamespace(connections=SimpleNamespace(all=lambda: []),
                             command_history=SimpleNamespace(view_service=ActivityView()))
    service = WebConnectionService(server, None, None, connection_history_store=store)
    result = service.get_machine_connection_history(
        'machine-test', client_id_search='NODE_', integrity='high',
        launch_mode='ide', termination_reason='timeout',
    )
    assert [item['client_id'] for item in result['sessions']] == ['node_A']
    assert result['sessions'][0]['activity_count'] == 2
    assert result['has_more'] is False
    assert result['connection_count'] == 3
    assert result['activity_count'] == 25
    assert result['unassigned_activity_count'] == 3
    assert result['filter_options']['integrity'] == ['high', 'low']
    database.close_thread_connection()


def test_invalid_snapshot_is_treated_as_unknown_for_filtering(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    store.record_connected({'machine_id': 'M', 'client_id': 'corrupt'})
    database.connection().execute(
        "UPDATE connection_sessions SET snapshot = 'not-json' WHERE client_id = 'corrupt'"
    )
    page = store.get_history('M', integrity='unknown', launch_mode='unknown')
    assert [row['client_id'] for row in page['sessions']] == ['corrupt']
    assert page['filter_options']['integrity'] == ['unknown']
    assert not page['has_more']
    database.close_thread_connection()

def test_termination_filter_excludes_online_blank_and_invalid_unknown(tmp_path):
    """Online has no termination cause; bad old values cannot become selectable causes."""
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    store.record_connected({
        'machine_id': 'M', 'client_id': 'online', 'connected_at': '2026-11-11T09:00:00+00:00',
    })
    store.record_connected({
        'machine_id': 'M', 'client_id': 'closed', 'connected_at': '2026-11-11T08:00:00+00:00',
    })
    store.record_disconnected({
        'machine_id': 'M', 'client_id': 'closed', 'disconnected_at': '2026-11-11T08:05:00+00:00',
    }, termination_reason='timeout')
    store.record_connected({
        'machine_id': 'M', 'client_id': 'unexplained', 'connected_at': '2026-11-11T06:00:00+00:00',
    })
    store.record_disconnected({
        'machine_id': 'M', 'client_id': 'unexplained', 'disconnected_at': '2026-11-11T06:05:00+00:00',
    })
    conn = database.connection()
    for client_id, reason in [('legacy-empty', ''), ('legacy-unknown', 'unknown')]:
        conn.execute(
            '''INSERT INTO connection_sessions (
                machine_id, client_id, connected_at, connected_at_ms, disconnected_at,
                disconnected_at_ms, last_seen_at, duration_ms, termination_reason,
                termination_detail, snapshot
            ) VALUES ('M', ?, '2026-11-11T07:00:00+00:00', 1,
                      '2026-11-11T07:01:00+00:00', 2, '', 60000, ?, '{}', '{}')''',
            (client_id, reason),
        )
    all_rows = store.get_history('M')
    assert all_rows['connection_count'] == 5
    assert len(all_rows['sessions']) == 5
    assert all_rows['filter_options']['termination_reason'] == ['timeout', 'unexpected_disconnect']
    assert [r['client_id'] for r in store.get_history('M', termination_reason='timeout')['sessions']] == ['closed']
    assert [r['client_id'] for r in store.get_history('M', termination_reason='unexpected_disconnect')['sessions']] == ['unexplained']
    assert store.get_history('M', termination_reason='unknown')['sessions'] == []
    assert store.get_history('M', client_id_search='online')['sessions'][0]['termination_reason'] == ''
    database.close_thread_connection()


def test_online_only_history_has_no_termination_filter_options(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    store.record_connected({
        'machine_id': 'M', 'client_id': 'online', 'connected_at': '2026-11-11T09:00:00+00:00',
    })
    page = store.get_history('M')
    assert page['filter_options']['termination_reason'] == []
    assert page['sessions'][0]['client_id'] == 'online'
    database.close_thread_connection()
