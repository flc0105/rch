"""Persistent data, artifact identity and document revisions."""

import json
from types import SimpleNamespace

import pytest

from server.application.artifact.artifact_registry_service import ArtifactRegistryService
from server.application.artifact.artifact_sqlite_catalog import ArtifactSqliteCatalog
from server.application.documents.document_library_service import DocumentLibraryService
from server.persistence.rch_database import RchDatabase


@pytest.fixture
def catalog(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'artifacts'
    root.mkdir()
    result = ArtifactSqliteCatalog(db, root)
    yield result, root
    db.close_thread_connection()


def test_catalog_rejects_noncanonical_paths_even_inside_root(catalog):
    store, root = catalog
    identifier = 'ab' * 16
    for wrong_path in ('objects/report.png', 'objects/ab/' + 'cd' * 16,
                       'preview/machine/test.png', 'objects/ab/' + identifier + '.png'):
        with pytest.raises(ValueError, match='does not match ID'):
            store.save({
                'artifact_id': identifier, 'artifact_type': 'preview',
                'original_name': 'example.png', 'size': 0,
                'saved_at': '2026-11-12 10:00:00', 'saved_path': wrong_path,
            })


@pytest.fixture
def artifact_registry(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    root = tmp_path / 'artifacts'
    file_path = root / 'objects' / 'a1' / ('a1' * 16)
    file_path.parent.mkdir(parents=True)
    file_path.write_text('original contents', encoding='utf-8')
    registry = ArtifactRegistryService(SimpleNamespace(
        database=database, artifacts_root_dir=str(root),
    ))
    registry.catalog.save({
        'artifact_id': 'a1' * 16, 'artifact_type': 'saved', 'category': 'downloads',
        'original_name': 'before.txt', 'size': file_path.stat().st_size,
        'machine_id': 'macbook', 'client_id': 'client-1',
        'saved_at': '2026-11-12 09:31:48', 'saved_path': 'objects/a1/' + ('a1' * 16),
        'extra': {},
    })
    yield registry, database, file_path
    database.close_thread_connection()


def test_rename_preserves_unicode_and_file_identity(artifact_registry):
    new_name = '报告 résumé 📁.json'
    registry, db, path = artifact_registry
    renamed = registry.rename_artifact('a1' * 16, new_name)
    assert renamed['original_name'] == new_name
    assert renamed['saved_at'] == '2026-11-12 09:31:48'
    assert renamed['stored_name'] == 'a1' * 16
    assert renamed['saved_path'] == 'objects/a1/' + ('a1' * 16)
    assert renamed['category'] == 'downloads'
    assert path.read_text(encoding='utf-8') == 'original contents'
    assert registry.catalog.get('a1' * 16)['original_name'] == new_name
    assert db.connection().execute('SELECT original_name FROM artifact_entries').fetchone()[0] == new_name


def test_existing_final_database_preserves_data_and_unrelated_tables(tmp_path):
    path = tmp_path / 'rch.db'
    db = RchDatabase(str(path))
    db.connection().execute("INSERT INTO settings(namespace,value_json) VALUES ('test', '{\"ok\":true}')")
    db.connection().execute('CREATE TABLE external_app_table (value TEXT)')
    db.connection().execute("INSERT INTO external_app_table VALUES ('retained')")
    db.close_thread_connection()
    reopened = RchDatabase(str(path))
    assert reopened.connection().execute("SELECT value_json FROM settings WHERE namespace='test'").fetchone()[0] == '{"ok":true}'
    assert reopened.connection().execute('SELECT value FROM external_app_table').fetchone()[0] == 'retained'
    reopened.close_thread_connection()


@pytest.fixture
def library(tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    return DocumentLibraryService({'notes': {'label': 'Notes', 'path': str(root)}}, 512 * 1024)


def test_conflict_preserves_external_changes(library, tmp_path):
    doc = library.create_document('notes', 'a.md')
    path = tmp_path / 'docs/a.md'
    path.write_bytes(b'external editor')
    with pytest.raises(ValueError, match='changed on disk'):
        library.save_document('notes', 'a.md', 'overwritten', 'utf-8', doc['sha256'])
    assert path.read_bytes() == b'external editor'


def test_document_write_cannot_escape_its_root(library, tmp_path):
    external = tmp_path / 'outside.md'
    external.write_bytes(b'outside data')
    with pytest.raises(ValueError):
        library.create_document('notes', '../outside.md')
    assert external.read_bytes() == b'outside data'


def test_activity_records_each_result_and_server_time_together(tmp_path, monkeypatch):
    from core.protocol.message_queue import ResultChunk
    from core.protocol.result_envelope import build_result_wire_event, result_wire_event
    from server.application.history.activity_coordinator import ActivityCoordinator
    from server.application.history.activity_definitions import ActivityOperation
    from server.application.history.command_dispatch_adapter import CommandDispatchAdapter
    from server.application.history.history_store import CommandHistoryStore

    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = CommandHistoryStore(db)
    coordinator = ActivityCoordinator(store)
    conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m', client_id='c'))
    request = {'type': 'control', 'domain': 'script', 'action': 'run',
               'payload': {'script_name': 'demo', 'source': 'print("demo")', 'params': {'source': 'argument'}}}
    entry_id = coordinator.prepare(conn, ActivityOperation('script', 'run', request['payload']))
    assert coordinator.dispatch(conn, entry_id, data=request)
    first = build_result_wire_event(1, {'event_type': 'chunk', 'message': 'First'})
    assert set(first) == {'type', 'id', 'event_type', 'message'}
    final = result_wire_event(1, 1, {'event_type': 'completed', 'status': 'success',
                                    'message': 'Finished', 'data': {'answer': 42}})
    assert set(final) == {'type', 'id', 'event_type', 'status', 'message', 'data'}
    adapter = CommandDispatchAdapter(coordinator, lambda _: conn)
    chunks = adapter.observe_result(conn, entry_id, request, [
        ResultChunk(1, first, 0, event=first),
        ResultChunk(1, final, 1, event=final),
    ])
    first_time = '2026-11-20T01:02:01.123+00:00'
    final_time = '2026-11-20T01:02:03.456+00:00'
    monkeypatch.setattr(store, '_now_iso', lambda: first_time)
    assert next(chunks).event is first
    running = store.view_service.get_execution_entry('m', entry_id)
    assert running['status'] == 'running'
    assert running['result'] == [first]
    assert running['recorded_at'] == [first_time]

    monkeypatch.setattr(store, '_now_iso', lambda: final_time)
    assert next(chunks).event is final
    assert list(chunks) == []
    assert request['payload']['source'] == 'print("demo")'

    entry = store.view_service.get_execution_entry('m', entry_id)
    assert entry['resolved']['payload'] == {'script_name': 'demo', 'params': {'source': 'argument'}}
    assert entry['result'] == [first, final]
    assert entry['recorded_at'] == [first_time, final_time]
    assert entry['status'] == 'success'
    stored, = db.connection().execute('SELECT result_json FROM activity_records WHERE activity_id = ?', (entry_id,)).fetchone()
    assert json.loads(stored) == {'result': [first, final], 'recorded_at': [first_time, final_time]}
    public_row = store.view_service.get_execution_history_page('m')['items'][0]
    assert public_row['activity_id'] == entry_id
    assert public_row['result_summary'] == 'Finished'
    assert not {'result', 'recorded_at', 'invocation', 'resolved'} & public_row.keys()
    assert not store.view_service.get_execution_entry('wrong-machine', entry_id)
    db.close_thread_connection()


def test_activity_result_budgets_preserve_packets_after_field_omission(tmp_path):
    from server.application.history.activity_coordinator import ActivityCoordinator
    from server.application.history.activity_definitions import ActivityOperation
    from server.application.history.history_store import CommandHistoryStore

    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = CommandHistoryStore(db)
    coordinator = ActivityCoordinator(store)
    conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m', client_id='c'))
    request = {'type': 'control', 'domain': 'remote_files', 'action': 'save_file',
               'payload': {'path': 'notes.txt', 'encoding': 'utf-8', 'content': 'new text'}}
    entry_id = coordinator.prepare(conn, ActivityOperation('remote_files', 'save_file', request['payload']))
    assert coordinator.dispatch(conn, entry_id, data=request)
    assert request['payload']['content'] == 'new text'

    chunk = {'type': 'result', 'id': 1, 'event_type': 'chunk'}
    for _ in range(257):
        coordinator.append_client_result(conn, entry_id, {**chunk, 'message': 'x'})
    exact = {**chunk, 'message': 'é' * 130943 + 'x', 'data': {'small': True}}
    coordinator.append_client_result(conn, entry_id, exact)
    entry = store.view_service.get_execution_entry('m', entry_id)
    assert len(entry['result']) == 258
    assert entry['result'][-1] == exact
    assert not entry['result_omitted']
    assert 'content' not in entry['resolved']['payload']

    coordinator.append_client_result(conn, entry_id, {**chunk, 'message': 'x', 'data': [1, 2]})
    final = {'type': 'result', 'id': 1, 'event_type': 'completed', 'status': 'success',
             'message': 'Done', 'data': {'large': 'x' * 262145},
             'references': [{'type': 'artifact', 'id': 'file'}]}
    coordinator.append_client_result(conn, entry_id, final)
    coordinator.finish(conn, entry_id, True)
    entry = store.view_service.get_execution_entry('m', entry_id)
    assert entry['result'][-3:] == [
        exact,
        {**chunk, 'data': [1, 2]},
        {key: value for key, value in final.items() if key not in ('message', 'data')},
    ]
    assert entry['result_omitted']
    assert entry['result_field_limit_bytes'] == 256 * 1024
    assert len(entry['recorded_at']) == len(entry['result'])
    assert entry['status'] == 'success'
    assert final['message'] == 'Done'
    db.close_thread_connection()


def test_activity_only_omits_large_data_and_does_not_persist_disconnect(tmp_path):
    from server.application.history.activity_coordinator import ActivityCoordinator
    from server.application.history.activity_definitions import ActivityOperation
    from server.application.history.command_dispatch_adapter import CommandDispatchAdapter
    from server.application.history.history_store import CommandHistoryStore
    from server.connection.runtime.session_runtime import ClientSessionRuntime

    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = CommandHistoryStore(db)
    coordinator = ActivityCoordinator(store)
    conn = SimpleNamespace(session_info=SimpleNamespace(machine_id='m', client_id='c'),
                           context=SimpleNamespace(), send_cancel=lambda *_: None)
    request = {'type': 'control', 'id': 42, 'domain': 'script', 'action': 'run', 'payload': {}}
    entry_id = coordinator.prepare(conn, ActivityOperation('script', 'run', {}))
    assert coordinator.dispatch(conn, entry_id, data=request)

    runtime = ClientSessionRuntime()
    queue = runtime.pending_results.register(42)
    packet = {'type': 'result', 'id': 42, 'event_type': 'chunk',
              'message': 'Small message', 'data': ['x' * 262145]}
    assert runtime.pending_results.deliver(42, packet)
    runtime.pending_results.close()
    chunks = runtime.wait_for_result(conn, 42, 'test', results=queue)
    adapter = CommandDispatchAdapter(coordinator, lambda _: conn)
    delivered = list(adapter.observe_result(conn, entry_id, request, chunks))
    assert delivered[0].event is packet
    assert delivered[-1].event is None

    entry = store.view_service.get_execution_entry('m', entry_id)
    assert entry['result'] == [{key: value for key, value in packet.items() if key != 'data'}]
    assert entry['result_omitted']
    assert entry['status'] == 'interrupted'
    db.close_thread_connection()
