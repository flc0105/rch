"""Client temp cleanup: real flat directories, live state, and preview/execute boundary."""

import json
import os
import time
from pathlib import Path

import pytest

from client.commands.common.services import client_cleanup_service as cleanup


@pytest.fixture
def managed(tmp_path, monkeypatch):
    root = tmp_path / 'rch_client_temp'
    root.mkdir()
    monkeypatch.setattr(cleanup, 'get_client_temp_root', lambda create=False: str(root))
    monkeypatch.setattr(cleanup, 'get_temp_category_dir', lambda category, create=False: str(root / category))
    monkeypatch.setattr(cleanup, 'get_client_log_path', lambda: '')
    monkeypatch.setattr(cleanup.tempfile, 'gettempdir', lambda: str(tmp_path))
    return root


def old(path, age=7200):
    ts = time.time() - age
    os.utime(path, (ts, ts))
    return path


def test_flat_category_scan_never_crosses_other_categories(managed):
    (managed / 'watchdog_heartbeats').mkdir()
    (managed / 'client_logs').mkdir()
    target = managed / 'preview_temp'
    target.mkdir()
    (target / 'finished.jpg').write_bytes(b'old')
    service = cleanup.ClientCleanupService()
    service.ITEMS = ('preview_temp',)
    plan = service.plan()['items'][0]
    assert plan['scanned_paths'] == [str(target), str(managed.parent / 'rat_preview_*')]
    assert [x['path'] for x in plan['paths']] == [str(target / 'finished.jpg')]
    assert not any('watchdog_heartbeats/preview_temp' in p for p in plan['scanned_paths'])
    assert (target / 'finished.jpg').exists()
    service.execute_plan({'items': [plan]}, {'preview_temp'})
    assert not (target / 'finished.jpg').exists()


def test_client_logs_keep_current_and_recent_instances(managed, monkeypatch):
    root = managed / 'client_logs'; root.mkdir()
    current = root / 'client_current'; current.mkdir()
    other = root / 'client_old'; other.mkdir()
    recent = root / 'client_recent'; recent.mkdir()
    for folder in (current, other, recent):
        (folder / 'client.log').write_text('log')
    for folder in (current, other):
        old(folder / 'client.log')
        old(folder)
    monkeypatch.setattr(cleanup, 'get_client_log_path', lambda: str(current / 'client.log'))
    svc = cleanup.ClientCleanupService(); svc.ITEMS = ('client_logs',)
    plan = svc.plan()
    item = plan['items'][0]
    assert item['scanned_paths'] == [str(root)]
    assert [x['path'] for x in item['paths']] == [str(other)]
    assert str(current) in item['skipped_paths'] and str(recent) in item['skipped_paths']
    result = svc.execute_plan(plan, {'client_logs'})
    assert result['removed_dirs'] and not other.exists()
    assert current.exists() and recent.exists()


def test_client_log_new_current_after_preview_is_not_removed(managed, monkeypatch):
    root = managed / 'client_logs'; root.mkdir()
    folder = root / 'client_prev'; folder.mkdir()
    file = folder / 'client.log'; file.write_text('old'); old(file); old(folder)
    current = {'path': ''}
    monkeypatch.setattr(cleanup, 'get_client_log_path', lambda: current['path'])
    svc = cleanup.ClientCleanupService(); svc.ITEMS = ('client_logs',)
    plan = svc.plan()
    assert len(plan['items'][0]['paths']) == 1
    current['path'] = str(file)
    executed = svc.execute_plan(plan, {'client_logs'})
    assert file.exists() and executed['removed_files'] == 0
    assert 'active' in executed['items'][0]['skipped_paths'][0]


def test_archive_and_clipboard_ignore_recent_writes(managed, monkeypatch):
    for category, stale_seconds in [('archive_temp', 900), ('clipboard_staging', 7200)]:
        root = managed / category; root.mkdir()
        stale = root / 'tmpold'; stale.mkdir()
        file = stale / 'record.zip'; file.write_bytes(b'x')
        old(file, stale_seconds); old(stale, stale_seconds)
        fresh = root / 'tmpnew'; fresh.mkdir()
        (fresh / 'still_writing').write_text('do not delete')
    monkeypatch.setattr(cleanup.sys, 'platform', 'linux')
    svc = cleanup.ClientCleanupService(); svc.ITEMS = ('archive_temp', 'clipboard_staging')
    plan = svc.plan()
    assert all(len(x['paths']) == 1 and x['paths'][0]['path'].endswith('tmpold') for x in plan['items'])
    svc.execute_plan(plan, set(svc.ITEMS))
    for category in svc.ITEMS:
        assert not (managed / category / 'tmpold').exists()
        assert (managed / category / 'tmpnew').exists()


def test_macos_clipboard_staging_not_considered_for_delete(managed, monkeypatch):
    root = managed / 'clipboard_staging'; root.mkdir()
    child = root / 'request1'; child.mkdir()
    old(child, 7200)
    monkeypatch.setattr(cleanup.sys, 'platform', 'darwin')
    svc = cleanup.ClientCleanupService(); svc.ITEMS = ('clipboard_staging',)
    item = svc.plan()['items'][0]
    assert item['paths'] == []
    assert child.exists()


def test_heartbeat_and_watchdog_session_skip_active_processes(managed, monkeypatch):
    hb = managed / 'watchdog_heartbeats'; hb.mkdir()
    active_hb = hb / 'client_local_watchdog_heartbeat_live.json'
    stale_hb = hb / 'client_local_watchdog_heartbeat_dead.json'
    active_hb.write_text(json.dumps({'pid': 801, 'ts': time.time()-7200}))
    stale_hb.write_text(json.dumps({'pid': 802, 'ts': time.time()-7200}))
    old(active_hb); old(stale_hb)
    sess = managed / 'watchdog_sessions'; sess.mkdir()
    active = sess / 'rch_process_watchdog_alive'; active.mkdir()
    dead = sess / 'rch_process_watchdog_dead'; dead.mkdir()
    for folder, pid in ((active, 801), (dead, 802)):
        marker = folder / 'ready.json'; marker.write_text(json.dumps({'pid': pid}))
        old(marker); old(folder)
    monkeypatch.setattr(cleanup.ClientCleanupService, '_pid_active', staticmethod(lambda pid: int(pid) == 801))
    svc = cleanup.ClientCleanupService(); svc.ITEMS = ('watchdog_heartbeats', 'watchdog_sessions')
    plan = svc.plan()
    assert [[x['path'] for x in g['paths']] for g in plan['items']] == [[str(stale_hb)], [str(dead)]]
    # Dead becomes active between preview and execution: do not remove it.
    monkeypatch.setattr(cleanup.ClientCleanupService, '_pid_active', staticmethod(lambda pid: True))
    executed = svc.execute_plan(plan, set(svc.ITEMS))
    assert stale_hb.exists() and dead.exists()
    assert executed['removed_files'] == 0 and executed['removed_dirs'] == 0


def test_new_categories_do_not_scan_legacy_cross_roots(managed):
    svc = cleanup.ClientCleanupService()
    names = {'archive_temp', 'client_logs', 'clipboard_staging', 'watchdog_heartbeats', 'watchdog_sessions'}
    assert names.issubset(set(svc.ITEMS))
    plan = svc.plan()
    for row in plan['items']:
        if row['name'] in names:
            assert row['scanned_paths'] == [str(managed / row['name'])]


def test_stale_watchdog_artifacts_removed_when_owner_exited(managed, monkeypatch):
    hb_dir = managed / 'watchdog_heartbeats'; hb_dir.mkdir()
    hb = hb_dir / 'client_local_watchdog_heartbeat_previous.json'
    hb.write_text(json.dumps({'pid': 123456, 'ts': time.time() - 1000}))
    old(hb)
    orphan_tmp = hb_dir / 'client_local_watchdog_heartbeat_lost.json.tmp'
    orphan_tmp.write_text('old'); old(orphan_tmp)
    sess_root = managed / 'watchdog_sessions'; sess_root.mkdir()
    sess = sess_root / 'rch_process_watchdog_old'; sess.mkdir()
    ready = sess / 'ready.json'; ready.write_text(json.dumps({'pid': 123456}))
    old(ready); old(sess)
    monkeypatch.setattr(cleanup.ClientCleanupService, '_pid_active', staticmethod(lambda pid: False))
    service = cleanup.ClientCleanupService()
    service.ITEMS = ('watchdog_heartbeats', 'watchdog_sessions')
    plan = service.plan()
    assert sum(len(x['paths']) for x in plan['items']) == 3
    result = service.execute_plan(plan, set(service.ITEMS))
    assert result['removed_files'] >= 3
    assert not hb.exists() and not orphan_tmp.exists() and not sess.exists()


def test_client_file_log_creates_no_owner_metadata(monkeypatch, tmp_path):
    import logging
    from client.runtime import client_logging
    folder = tmp_path / 'client_logs'; folder.mkdir()
    monkeypatch.setattr(client_logging, 'get_temp_category_dir', lambda *a, **k: str(folder))
    root = logging.getLogger()
    previous = list(root.handlers)
    try:
        path = client_logging.install_client_file_logging()
        assert path and Path(path).exists()
        assert set(p.name for p in Path(path).parent.iterdir()) == {'client.log'}
    finally:
        for handler in list(root.handlers):
            if handler not in previous:
                root.removeHandler(handler)
                handler.close()


def test_no_confirm_skips_unverifiable_other_client_logs(monkeypatch):
    from types import SimpleNamespace
    from client.commands.common.mixins.update_ops import CommandUpdateMixin

    plan = {'items': [
        {'name': 'client_logs', 'paths': [{'path': '/tmp/stale-client'}],
         'removed_files': 1, 'removed_dirs': 1, 'bytes_freed': 200, 'scanned_paths': []},
        {'name': 'preview_temp', 'paths': [{'path': '/tmp/old-preview'}],
         'removed_files': 1, 'removed_dirs': 0, 'bytes_freed': 30, 'scanned_paths': []},
    ]}
    monkeypatch.setattr(cleanup.ClientCleanupService, 'plan', lambda self: plan)
    chosen = []
    monkeypatch.setattr(cleanup.ClientCleanupService, 'execute_plan', lambda self, plan, selected:
                        (chosen.append(selected), {'error_count': 0, 'items': [],
                                                   'removed_files': 0, 'removed_dirs': 0,
                                                   'bytes_freed': 0})[1])
    host = SimpleNamespace(_set_timeout=lambda *a: None,
                           _checkpoint=lambda *a: None,
                           _get_current_bundle_release_dir=lambda *a: '',
                           _format_client_cleanup_result=lambda result: 'ok')
    code, output = CommandUpdateMixin.clean(host, '--no-confirm')
    assert code == 1 and chosen == [{'preview_temp'}]
