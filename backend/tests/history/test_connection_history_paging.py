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
                connection_state, termination_reason, termination_detail_json,
                tracking_source, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 100, 'offline', '', '{}', 'connection_lifecycle', ?)""",
            ('machine-1', f'client-{i:02}', '2026-11-05T10:00:00', i + 1,
             '2026-11-05T10:01:00', i + 2, '2026-11-05T10:01:00',
             '{"hostname":"host-%02d"}' % i),
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
        assert first['next_offset'] == 20
        assert len(decoded) == 20

        second = store.get_history('machine-1', limit=20, offset=20)
        assert [r['client_id'] for r in second['sessions']] == [f'client-{i:02}' for i in range(24, 4, -1)]
        assert second['has_more'] is True
        assert second['next_offset'] == 40
        assert len(decoded) == 40

        last = store.get_history('machine-1', limit=20, offset=40)
        assert [r['client_id'] for r in last['sessions']] == [f'client-{i:02}' for i in range(4, -1, -1)]
        assert last['has_more'] is False
        assert len(decoded) == 45
        assert all('hostname' in row for page in (first, second, last) for row in page['sessions'])
        page_queries = [q.lower() for q in queries if 'select * from connection_sessions' in q.lower()]
        assert len(page_queries) == 3
        assert all('limit' in q and 'offset' in q for q in page_queries)
        assert 'limit 21 offset 0' in page_queries[0]
        assert 'limit 21 offset 20' in page_queries[1]
        assert 'limit 21 offset 40' in page_queries[2]
    finally:
        conn.set_trace_callback(None)
        database.close_thread_connection()
