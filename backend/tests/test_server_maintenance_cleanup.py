"""Server-only cleanup plan, protected resources and SQLite reclamation."""
import os
import threading
import time
from pathlib import Path
from dataclasses import replace

import pytest

from server.application.agent.agent_output_registry import AgentOutputRegistry
from server.application.maintenance.cleanup_plan import Candidate
from server.application.maintenance.server_cleanup_service import ServerCleanupService
from server.application.preferences.notification_history_store import NotificationHistoryStore
from server.application.preferences.settings_store import SettingsStore
from server.application.web.notification_history_api import WebNotificationHistoryApi
from server.persistence.rch_database import RchDatabase


class Artifacts:
    """Test double for the Artifact business boundary; real files remain on disk."""
    def __init__(self, root):
        self.upload_tmp_dir = str(root / 'upload_tmp')
        self.reserved = set()
        self.orphans = set()
        self.tcp = set()
        self.previews = {}
        self.opened = set()

    def is_upload_temp_reserved(self, path):
        return path in self.reserved

    def maintenance_residue_paths(self, kind):
        return list(self.orphans if kind == 'orphan' else self.tcp)

    def is_orphan_artifact_path(self, path):
        return path in self.orphans

    def delete_upload_residue_for_cleanup(self, directory, remove):
        assert directory not in self.reserved
        remove()

    def delete_orphan_for_cleanup(self, path, remove):
        assert path in self.orphans
        remove()

    def missing_artifact_count(self):
        return 0

    def startup_preview_entries(self):
        return list(self.previews.values())

    def is_cleanup_preview(self, key):
        return key in self.previews and key not in self.opened

    def delete_preview_for_cleanup(self, key, saved_at, unchanged):
        assert self.is_cleanup_preview(key) and unchanged()
        Path(self.previews.pop(key)[1]).unlink()


def create_file(path, data=b'content', days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if days:
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def setup(tmp_path):
    database = RchDatabase(str(tmp_path / 'rch.db'))
    artifact = Artifacts(tmp_path / 'web_files' / 'artifacts')
    registry = AgentOutputRegistry(str(tmp_path / 'agent_output'), database)
    store = NotificationHistoryStore(database)
    api = WebNotificationHistoryApi(store)
    prefs = SettingsStore(database, 'server_cleanup')
    def make():
        return ServerCleanupService(event_bus=None, notification_history_api=api, artifact_service=artifact,
            agent_output_registry=registry, cleanup_items=('agent_build_temp', 'agent_transient_outputs', 'preview_cache', 'upload_tmp', 'cleanup_logs', 'tcp_transfer_residue', 'bootstrap_temp'),
            start_delay_seconds=0, log_root_dir=str(tmp_path / 'cleanup_logs'), settings_store=prefs,
            database=database, runtime_dir=tmp_path)
    yield tmp_path, database, artifact, store, make
    database.close_thread_connection()


def group(plan, key):
    return next(item for item in plan['groups'] if item['key'] == key)


def wait_run(service, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        if run['state'] != 'running':
            assert run['state'] == 'completed', run
            return run['result']
        time.sleep(.01)
    pytest.fail('cleanup run did not finish')


def execute(service, plan, ids):
    return wait_run(service, service.execute(plan['plan_id'], ids)['run_id'])


def test_manual_plan_is_one_use_and_removes_only_selected_files(setup):
    root, _, artifacts, _, make = setup
    a = create_file(root / 'cleanup_logs' / 'server_cleanup_one.log', b'a')
    b = create_file(root / 'cleanup_logs' / 'server_cleanup_two.log', b'bb')
    keep = create_file(root / 'server.log')
    service = make()
    plan = service.preview()
    entries = group(plan, 'cleanup_logs')['entries']
    assert {e['name'] for e in entries} == {a.name, b.name}
    assert not any('history' in g['key'] for g in plan['groups'])
    with pytest.raises(ValueError, match='Unknown cleanup candidate'):
        service.execute(plan['plan_id'], [str(keep)])
    selected = next(e['id'] for e in entries if e['name'] == a.name)
    result = execute(service, plan, [selected])
    assert result['removed_files'] == 1 and result['bytes_freed'] == 1
    assert not a.exists() and b.exists() and keep.exists()
    assert Path(service.get_log_path(result['run_id'])).is_file()
    with pytest.raises(ValueError, match='expired'):
        service.execute(plan['plan_id'], [selected])


def test_changed_tree_and_current_instance_upload_are_preserved(setup):
    root, _, artifacts, _, make = setup
    old = create_file(Path(artifacts.upload_tmp_dir) / ('a'*32) / 'x.bin')
    active = create_file(Path(artifacts.upload_tmp_dir) / ('b'*32) / 'y.bin')
    artifacts.reserved.add(str(active.parent))
    service = make()
    new = create_file(Path(artifacts.upload_tmp_dir) / ('c'*32) / 'new.bin')
    plan = service.preview()
    entries = group(plan, 'upload_tmp')['entries']
    assert len(entries) == 1 and entries[0]['children'][0]['path'] == 'x.bin'
    added = create_file(old.parent / 'new.txt')
    result = execute(service, plan, [entries[0]['id']])
    assert result['skipped_count'] == 1 and old.exists() and active.exists() and new.exists() and added.exists()


def test_reservation_rechecked_and_safe_directory_removal(setup):
    root, _, artifacts, _, make = setup
    old = create_file(Path(artifacts.upload_tmp_dir) / ('d'*32) / 'nested' / 'x.bin')
    directory = old.parent.parent
    service = make()
    plan = service.preview()
    entry = group(plan, 'upload_tmp')['entries'][0]
    artifacts.reserved.add(str(directory))
    assert execute(service, plan, [entry['id']])['skipped_count'] == 1
    artifacts.reserved.clear()
    plan = service.preview()
    result = execute(service, plan, [group(plan, 'upload_tmp')['entries'][0]['id']])
    assert result['removed_dirs'] == 2 and result['removed_files'] == 1 and not directory.exists()


def test_symlink_hardlink_and_unknown_files_are_not_removed(tmp_path):
    outside = create_file(tmp_path / 'outside')
    directory = tmp_path / 'managed'
    directory.mkdir()
    (directory / 'link').symlink_to(outside)
    with pytest.raises(ValueError):
        Candidate.file('test', directory, directory)
    (directory / 'link').unlink()
    os.link(outside, directory / 'hard')
    with pytest.raises(ValueError):
        Candidate.file('test', directory, directory)
    assert outside.read_bytes() == b'content'


def test_old_logs_and_auto_settings_persist_without_deleting_records(setup):
    root, db, _, notifications, make = setup
    old = create_file(root / 'server.log.1', days=40)
    recent = create_file(root / 'server.log.2')
    loader = create_file(root / 'logs' / 'go_loader_20200101-00.log', days=40)
    current = create_file(root / 'logs' / time.strftime('go_loader_%Y%m%d-%H.log'))
    bootstrap = create_file(root / 'bootstrap_tmp' / 'bootstrap_old.py')
    build = create_file(root / 'agent_build_tmp' / 'agent_build_old' / 'build.txt')
    notifications.add_notification({'title': 'Keep', 'shown_at': '2020-01-01T00:00:00Z'})
    service = make()
    policy = service.get_settings()
    assert not policy['categories']['notifications']['enabled'] and 'orphan_artifacts' not in policy['categories']
    policy['categories']['server_rotated_logs']['enabled'] = True
    policy['categories']['go_loader_logs']['enabled'] = True
    service.save_settings(policy)
    service = make()
    assert service.get_settings() == policy
    result = service.run_cleanup()
    assert result['removed_files'] == 4
    assert not old.exists() and not loader.exists() and not bootstrap.exists() and not build.exists()
    assert recent.exists() and current.exists()
    assert notifications.get_history()['total_count'] == 1
    policy['enabled'] = False
    service.save_settings(policy)
    assert make().run_cleanup() is None


def test_notification_scan_is_complete_and_revalidates_records(setup):
    _, db, _, store, make = setup
    for index in range(35):
        store.add_notification({'id': str(index), 'title': f'Notice {index}', 'shown_at': '2020-01-01T00:00:00Z'})
    service = make()
    plan = service.preview()
    group_data = group(plan, 'notifications')
    assert group_data['records'] == 35 and group_data['size'] == 0
    chosen = next(e for e in group_data['entries'] if e['name'] == 'Notice 0')
    db.execute('UPDATE notifications SET title=? WHERE id=?', ('Changed', '0'))
    result = execute(service, plan, [chosen['id']])
    assert result['removed_records'] == 0 and result['skipped_count'] == 1
    plan = service.preview()
    result = execute(service, plan, [e['id'] for e in group(plan, 'notifications')['entries']])
    assert result['removed_records'] == 35 and result['bytes_freed'] == 0


def test_orphan_is_manual_only_and_registered_again_is_protected(setup):
    root, _, artifacts, _, make = setup
    orphan = create_file(root / 'orphan')
    tcp = create_file(root / 'tcp')
    artifacts.orphans.add(str(orphan)); artifacts.tcp.add(str(tcp))
    service = make()
    service.run_cleanup()
    assert orphan.exists() and not tcp.exists()
    plan = service.preview()
    entry = group(plan, 'orphan_artifacts')['entries'][0]
    artifacts.orphans.clear()
    result = execute(service, plan, [entry['id']])
    assert result['skipped_count'] == 1 and orphan.exists()


def test_stop_remaining_and_mutual_exclusion(setup):
    root, _, _, _, make = setup
    first = create_file(root / 'cleanup_logs' / 'server_cleanup_first.log')
    second = create_file(root / 'cleanup_logs' / 'server_cleanup_second.log')
    service = make()
    started = threading.Event(); release = threading.Event()
    provider = service._providers['cleanup_logs']
    def pause(item, result):
        started.set()
        assert release.wait(3)
        provider.delete(item, result)
    service._providers['cleanup_logs'] = replace(provider, delete=pause)
    plan = service.preview()
    run = service.execute(plan['plan_id'], [e['id'] for e in group(plan, 'cleanup_logs')['entries']])
    assert started.wait(2)
    try:
        with pytest.raises(ValueError, match='busy'):
            service.optimize_database()
        assert not service.reserve_stop()
        service.cancel_run(run['run_id'])
    finally:
        release.set()
    result = wait_run(service, run['run_id'])
    assert result['stopped_count'] == 1 and result['removed_files'] == 1
    assert not first.exists() and second.exists()


def test_database_vacuum_reclaims_pages_preserves_records(setup):
    _, db, _, _, make = setup
    db.execute('CREATE TABLE maintenance_test(id INTEGER PRIMARY KEY, value BLOB)')
    with db.transaction() as conn:
        conn.executemany('INSERT INTO maintenance_test(value) VALUES (?)', [(b'x' * 4096,)] * 300)
    db.execute('DELETE FROM maintenance_test WHERE id>1')
    before = db.space_info()
    assert before['reusable_bytes'] > 0
    result = make().optimize_database()
    assert result['bytes_reclaimed'] > 0
    assert result['after']['reusable_bytes'] == 0
    assert db.fetch_one('SELECT COUNT(*) FROM maintenance_test')[0] == 1
    assert db.fetch_one('SELECT length(value) FROM maintenance_test')[0] == 4096
    assert db.integrity_check() == 'ok'


def test_real_artifact_catalog_residue_and_live_preview(tmp_path):
    pytest.importorskip('werkzeug')
    from types import SimpleNamespace
    from server.application.artifact.artifact_registry_service import ArtifactRegistryService
    db = RchDatabase(str(tmp_path / 'rch.db'))
    registry = ArtifactRegistryService(SimpleNamespace(database=db, artifacts_root_dir=str(tmp_path / 'artifacts')))
    try:
        root = tmp_path / 'artifacts'
        orphan = create_file(root / 'objects' / 'aa' / ('a'*32))
        tcp = create_file(root / 'objects' / 'aa' / '.rch-transfer-old')
        wrong_shard = create_file(root / 'objects' / 'aa' / ('b'*32))
        preview = registry.allocate_artifact_path('preview', 'machine', 'preview.txt')
        create_file(Path(preview['file_path']))
        registry.register_existing_artifact(artifact_type='preview', category='', hostname='', machine_id='machine',
            original_name='preview.txt', file_path=preview['file_path'], artifact_id=preview['artifact_id'])
        assert registry.maintenance_residue_paths('orphan') == [str(orphan)]
        assert registry.maintenance_residue_paths('tcp') == [str(tcp)]
        assert not registry.is_orphan_artifact_path(wrong_shard)
        assert not registry.is_orphan_artifact_path(preview['file_path'])
        assert len(registry.startup_preview_entries()) == 1
        registry.get_artifact_file_path(preview['artifact_id'])
        assert not registry.is_cleanup_preview(preview['artifact_id'])
        with pytest.raises(ValueError):
            registry.delete_preview_for_cleanup(preview['artifact_id'], '', lambda: True)
    finally:
        db.close_thread_connection()


def test_partial_scan_keeps_safe_candidates(setup):
    root, _, artifacts, _, make = setup
    unsafe = Path(artifacts.upload_tmp_dir) / ('a' * 32)
    unsafe.mkdir(parents=True)
    outside = create_file(root / 'protected.txt')
    (unsafe / 'link').symlink_to(outside)
    safe = create_file(Path(artifacts.upload_tmp_dir) / ('b' * 32) / 'x.txt')
    service = make()
    plan = service.preview()
    uploads = group(plan, 'upload_tmp')
    assert uploads['error'] and uploads['count'] == 1
    result = execute(service, plan, [uploads['entries'][0]['id']])
    assert result['removed_files'] == 1 and not safe.exists() and outside.exists()
    assert (unsafe / 'link').is_symlink()


def test_database_optimization_refuses_insufficient_disk(setup, monkeypatch):
    _, db, _, _, make = setup
    before = db.space_info()
    monkeypatch.setattr(db, 'space_info', lambda: {**before, 'disk_free_bytes': 0})
    with pytest.raises(ValueError, match='Insufficient free disk'):
        make().optimize_database()
    assert db.integrity_check() == 'ok'


def test_maintenance_routes_require_admin_static_token(monkeypatch):
    pytest.importorskip('flask')
    from flask import Flask
    from types import SimpleNamespace
    from server.config import config
    from server.web.routes.server_cleanup import create_server_cleanup_blueprint
    from server.runtime.server_lifecycle import ServerLifecycle
    monkeypatch.setattr(config, 'ADMIN_API_TOKEN', 'maintenance-test-token')
    cleanup = SimpleNamespace(summary=lambda: {'bytes': 0}, execute=lambda payload: payload)
    server = SimpleNamespace(web_service=SimpleNamespace(server_cleanup_api=cleanup))
    lifecycle = ServerLifecycle()
    app = Flask(__name__)
    app.register_blueprint(create_server_cleanup_blueprint(server, lifecycle))
    client = app.test_client()
    assert client.get('/api/server-cleanup/summary').status_code == 403
    assert client.post('/api/server-cleanup/execute', json={}).status_code == 403
    headers = {'Authorization': 'Bearer maintenance-test-token'}
    assert client.get('/api/server-cleanup/summary', headers=headers).status_code == 200
    lifecycle.reserve('restart')
    assert client.post('/api/server-cleanup/execute', json={}, headers=headers).status_code == 409


def test_restart_reservation_blocks_new_cleanup_and_startup_timer(setup):
    root, _, _, _, make = setup
    path = create_file(root / 'cleanup_logs' / 'server_cleanup_old.log', days=20)
    service = make()
    plan = service.preview()
    entries = group(plan, 'cleanup_logs')['entries']
    assert entries and service.reserve_stop()
    assert not service.reserve_stop()
    with pytest.raises(ValueError, match='pending'):
        service.execute(plan['plan_id'], [entries[0]['id']])
    with pytest.raises(ValueError, match='pending'):
        service.optimize_database()
    assert service.run_cleanup() is None
    assert path.exists()
