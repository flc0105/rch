from datetime import datetime, timezone
from types import SimpleNamespace

from core.utils.datetime_utils import format_iso_datetime_utc, parse_iso_datetime
from server.application.connection.connection_history_store import ConnectionHistoryStore
from server.application.connection.recent_device_store import RecentDeviceStore
from server.application.connection.connection_service import WebConnectionService
from server.connection.services.heartbeat_service import SessionHeartbeatService
from server.persistence.rch_database import RchDatabase


def test_iso_datetime_parser_normalizes_offsets_to_utc():
    value = '2026-11-04T12:00:00+08:00'
    parsed = parse_iso_datetime(value)

    assert parsed == datetime(2026, 11, 4, 4, 0, tzinfo=timezone.utc)
    assert format_iso_datetime_utc(value) == '2026-11-04T04:00:00+00:00'
    assert format_iso_datetime_utc('2026-11-04T04:00:00Z') == '2026-11-04T04:00:00+00:00'
    assert parse_iso_datetime('2026-11-04T04:00:00') is None
    assert format_iso_datetime_utc('2026-11-04T04:00:00') == ''


def test_connection_state_compares_utc_aware_timestamps():
    service = WebConnectionService(SimpleNamespace(), None, None)
    service._now = lambda: datetime(2026, 11, 4, 4, 0, 46, tzinfo=timezone.utc)
    session = SimpleNamespace(context=SimpleNamespace(
        disconnected_at='',
        last_seen_at='2026-11-04T12:00:00+08:00',
    ))

    assert service._build_connection_state(session) == 'stale'


def test_connection_payload_serializes_all_lifecycle_times_as_utc():
    info = SimpleNamespace(
        client_id='client-C', addr='127.0.0.1:9999', hostname='host-C',
        machine_id='machine-C', machine_fingerprint_basis='basis',
        os_type='Linux', os_alias='linux', os_ver='test', os_name='Linux',
        os_full='Linux test', arch='x86_64', manufacturer='', model='',
        integrity='user', cwd='/', build_version='dev', client_revision='',
        get_extra=lambda _key, _default=None: None,
    )
    context = SimpleNamespace(
        connected_at='2026-11-04T12:00:00+08:00',
        disconnected_at='',
        last_seen_at='2026-11-04T12:00:30+08:00',
        last_heartbeat_sent_at='2026-11-04T12:00:20+08:00',
        last_heartbeat_ack_at='2026-11-04T12:00:30+08:00',
        last_rtt_ms=10,
    )
    session = SimpleNamespace(session_info=info, context=context)
    service = WebConnectionService(SimpleNamespace(), None, None)

    payload = service.serialize_connection(session)

    assert payload['connected_at'] == '2026-11-04T04:00:00+00:00'
    assert payload['last_seen_at'] == '2026-11-04T04:00:30+00:00'
    assert payload['last_heartbeat_sent_at'] == '2026-11-04T04:00:20+00:00'
    assert payload['last_heartbeat_ack_at'] == '2026-11-04T04:00:30+00:00'


def test_heartbeat_timestamps_are_utc_and_rtt_accepts_utc_echo():
    context = SimpleNamespace(
        connected_at='', disconnected_at='', last_seen_at='',
        last_heartbeat_sent_at='', last_heartbeat_ack_at='',
        last_heartbeat_id=None, last_rtt_ms=None, on_heartbeat_updated=None,
    )
    sent = []
    session = SimpleNamespace(
        context=context,
        command_channel=SimpleNamespace(generate_message_id=lambda: 17),
        send=sent.append,
    )
    heartbeat = SessionHeartbeatService(session)

    heartbeat.mark_connected()
    heartbeat.send_heartbeat()
    heartbeat.handle_heartbeat_ack({'id': 17, 'server_ts': sent[0]['ts']})

    assert context.connected_at.endswith('+00:00')
    assert context.last_seen_at.endswith('+00:00')
    assert context.last_heartbeat_sent_at.endswith('+00:00')
    assert context.last_heartbeat_ack_at.endswith('+00:00')
    assert context.last_rtt_ms is not None
    assert context.last_rtt_ms >= 0


def test_history_store_rejects_legacy_naive_timestamp_and_keeps_new_utc_heartbeat(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    store = ConnectionHistoryStore(database)
    try:
        store.record_connected({
            'machine_id': 'machine-A',
            'client_id': 'client-A',
            'connected_at': '2026-11-04T04:00:00+00:00',
            'last_seen_at': '2026-11-04T04:00:00+00:00',
        })
        database.connection().execute(
            "UPDATE connection_sessions SET connected_at = ? WHERE machine_id = ? AND client_id = ?",
            ('2026-11-04T04:00:00', 'machine-A', 'client-A'),
        )
        store.record_heartbeat({
            'machine_id': 'machine-A',
            'client_id': 'client-A',
            'connected_at': '2026-11-04T04:00:00+00:00',
            'last_seen_at': '2026-11-04T04:00:30+00:00',
        })

        history = store.get_history('machine-A')
        session = history['sessions'][0]
        assert session['connected_at'] == ''
        assert session['last_seen_at'].endswith('+00:00')
        assert history['tracking_started_at'] == ''
        assert session['connection_state'] == 'online'

        store.record_connected({
            'machine_id': 'machine-A',
            'client_id': 'client-A',
            'connected_at': '2026-11-04T04:01:00+00:00',
            'last_seen_at': '2026-11-04T04:01:00+00:00',
        })
        refreshed = store.get_history('machine-A')['sessions'][0]
        assert refreshed['connected_at'] == '2026-11-04T04:01:00+00:00'
    finally:
        database.close_thread_connection()


def test_recent_device_store_persists_connection_times_in_utc(tmp_path):
    database = RchDatabase(str(tmp_path / 'recent.db'))
    store = RecentDeviceStore(database)
    try:
        store.upsert_from_connection({
            'machine_id': 'machine-B',
            'client_id': 'client-B',
            'hostname': 'host-B',
            'connection_state': 'online',
            'connected_at': '2026-11-04T12:00:00+08:00',
            'last_seen_at': '2026-11-04T12:00:30+08:00',
        })

        record = store.list_recent_devices()[0]
        assert record['connected_at'] == '2026-11-04T04:00:00+00:00'
        assert record['last_seen_at'] == '2026-11-04T04:00:30+00:00'
    finally:
        database.close_thread_connection()


def test_legacy_naive_disconnect_time_does_not_turn_offline_history_online(tmp_path):
    database = RchDatabase(str(tmp_path / 'offline.db'))
    store = ConnectionHistoryStore(database)
    try:
        store.record_connected({
            'machine_id': 'machine-D',
            'client_id': 'client-D',
            'connected_at': '2026-11-04T04:00:00+00:00',
            'last_seen_at': '2026-11-04T04:00:00+00:00',
        })
        store.record_disconnected({
            'machine_id': 'machine-D',
            'client_id': 'client-D',
            'disconnected_at': '2026-11-04T04:01:00+00:00',
        }, termination_reason='client_exit')
        database.connection().execute(
            "UPDATE connection_sessions SET disconnected_at = ? WHERE machine_id = ? AND client_id = ?",
            ('2026-11-04T04:01:00', 'machine-D', 'client-D'),
        )

        session = store.get_history('machine-D')['sessions'][0]
        assert session['disconnected_at'] == ''
        assert session['connection_state'] == 'offline'
    finally:
        database.close_thread_connection()
