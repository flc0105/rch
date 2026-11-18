"""v1.109 Clean reporting: grouped progress and authoritative aggregate status."""

import os
from types import SimpleNamespace

import pytest

from client.commands.common.services import client_cleanup_service as cleanup
from client.commands.shell.common import maintenance as update_ops
from client.commands.shell.common.maintenance import ShellMaintenanceCommands


@pytest.fixture
def managed_cleanup(tmp_path, monkeypatch):
    root = tmp_path / 'rch_client_temp'
    root.mkdir()
    monkeypatch.setattr(cleanup, 'get_client_temp_root', lambda create=False: str(root))
    monkeypatch.setattr(cleanup, 'get_temp_category_dir', lambda category, create=False: str(root / category))
    monkeypatch.setattr(cleanup, 'get_client_log_path', lambda: '')
    return root


def make_host(progress):
    return SimpleNamespace(
        _checkpoint=lambda *args, **kwargs: None,
        _set_timeout=lambda *args, **kwargs: None,
        _get_current_bundle_release_dir=lambda *args, **kwargs: '',
        emit_progress=lambda message, *, level=None: progress.append((level, message)),
    )


def test_cleanup_service_emits_grouped_scan_and_clean_progress(managed_cleanup):
    category = managed_cleanup / 'preview_temp'
    category.mkdir()
    (category / 'one.tmp').write_bytes(b'one')
    (category / 'two.tmp').write_bytes(b'two-two')
    events = []
    service = cleanup.ClientCleanupService(
        progress_callback=lambda phase, item: events.append((phase, item['name'])),
    )
    service.ITEMS = ('preview_temp',)

    plan = service.plan()
    assert events == [('scan_completed', 'preview_temp')]
    assert len(plan['items'][0]['paths']) == 2

    result = service.execute_plan(plan, {'preview_temp'})
    assert events == [
        ('scan_completed', 'preview_temp'),
        ('clean_started', 'preview_temp'),
        ('clean_completed', 'preview_temp'),
    ]
    assert result['removed_files'] == 2
    assert result['error_count'] == 0


def test_cleanup_service_continues_after_one_delete_fails_and_counts_partial(managed_cleanup, monkeypatch):
    category = managed_cleanup / 'preview_temp'
    category.mkdir()
    good = category / 'good.tmp'
    denied = category / 'denied.tmp'
    good.write_bytes(b'good')
    denied.write_bytes(b'denied')
    service = cleanup.ClientCleanupService()
    service.ITEMS = ('preview_temp',)
    plan = service.plan()

    original_remove = os.remove
    def remove(path, *args, **kwargs):
        if os.fspath(path) == str(denied):
            raise PermissionError('Permission denied')
        return original_remove(path, *args, **kwargs)
    monkeypatch.setattr(cleanup.os, 'remove', remove)

    result = service.execute_plan(plan, {'preview_temp'})
    assert not good.exists()
    assert denied.exists()
    assert result['removed_files'] == 1
    assert result['error_count'] == 1
    status, message = ShellMaintenanceCommands._cleanup_completion(result)
    assert status == 'partial'
    assert '1 files' in message and '1 failed' in message


class FakeCleanupService:
    def __init__(self, *, checkpoint=None, current_bundle_resolver=None, progress_callback=None):
        self.progress_callback = progress_callback
        self.executed = False
        self.plan_data = {'items': []}
        self.result_data = {'items': [], 'removed_files': 0, 'removed_dirs': 0,
                            'bytes_freed': 0, 'error_count': 0}

    def plan(self):
        for item in self.plan_data['items']:
            if self.progress_callback:
                self.progress_callback('scan_completed', item)
        return self.plan_data

    def execute_plan(self, plan, selected):
        self.executed = True
        for item in plan['items']:
            if item['name'] not in selected:
                continue
            if self.progress_callback:
                self.progress_callback('clean_started', item)
                result_item = dict(item)
                result_item.update(self.result_data.get('items_by_name', {}).get(item['name'], {}))
                self.progress_callback('clean_completed', result_item)
        return self.result_data


def test_clean_returns_partial_completed_and_waits_before_preview(monkeypatch):
    progress = []
    host = make_host(progress)
    service = FakeCleanupService()
    service.plan_data = {'items': [{
        'name': 'bundle_old_releases', 'paths': [{'path': '/releases/old'}],
        'scanned_paths': ['/releases'], 'removed_files': 12, 'removed_dirs': 3,
        'bytes_freed': 4096, 'errors': [], 'skipped_paths': [], 'prune_dirs': [],
    }]}
    service.result_data = {
        'items': [], 'removed_files': 12, 'removed_dirs': 3,
        'bytes_freed': 4096, 'error_count': 2,
        'items_by_name': {'bundle_old_releases': {
            'removed_files': 12, 'removed_dirs': 3, 'bytes_freed': 4096,
            'errors': ['permission denied', 'permission denied'],
        }},
    }
    def make_service(**kwargs):
        service.progress_callback = kwargs.get('progress_callback')
        return service
    monkeypatch.setattr(update_ops, 'ClientCleanupService', make_service)
    preview_calls = []

    class Interactions:
        def __init__(self, owner):
            pass
        def select_preview_rows(self, message, preview, *, title):
            preview_calls.append((list(progress), preview))
            return ['bundle_old_releases']

    monkeypatch.setattr('client.runtime.execution.interaction_service.CommandInteractions', Interactions)
    code, payload = ShellMaintenanceCommands.clean(host, '')

    assert code == 1
    assert payload['event_type'] == 'completed' and payload['status'] == 'partial'
    assert '12 files and 3 directories deleted' in payload['message']
    assert '2 failed' in payload['message']
    assert preview_calls
    assert preview_calls[0][0][-1] == ('info', 'Waiting for cleanup approval...')
    preview = preview_calls[0][1]
    assert preview['columns'] == [
        {'key': 'category', 'label': 'Cleanup item'},
        {'key': 'directory', 'label': 'Directory'},
        {'key': 'files', 'label': 'Files'},
        {'key': 'directories', 'label': 'Directories'},
        {'key': 'size', 'label': 'Size'},
    ]
    assert preview['rows'][0]['directory'] == '/releases'
    assert 'row_details' not in preview
    assert all('/releases/old' not in message for _, message in progress)
    assert ('warning', 'bundle_old_releases: partially cleaned — 12 files, 3 directories deleted; 4.00KB freed; 2 failed') in progress


def test_clean_scan_error_fails_without_opening_preview_or_deleting(monkeypatch):
    progress = []
    host = make_host(progress)
    service = FakeCleanupService()
    service.plan_data = {'items': [{
        'name': 'bundle_old_releases', 'paths': [{'path': '/releases/old'}],
        'scanned_paths': ['/releases'], 'removed_files': 12, 'removed_dirs': 3,
        'bytes_freed': 4096, 'errors': ['Permission denied'],
    }]}
    def make_service(**kwargs):
        service.progress_callback = kwargs.get('progress_callback')
        return service
    monkeypatch.setattr(update_ops, 'ClientCleanupService', make_service)

    code, payload = ShellMaintenanceCommands.clean(host, '')

    assert code == 0
    assert payload['event_type'] == 'completed' and payload['status'] == 'error'
    assert 'nothing was deleted' in payload['message']
    assert not service.executed
    assert not any('Waiting for cleanup approval' in message for _, message in progress)
    assert ('error', 'Unable to scan bundle_old_releases (1 errors)') in progress


@pytest.mark.parametrize(('removed_files', 'removed_dirs', 'error_count', 'expected'), [
    (0, 0, 0, 'success'),
    (5, 1, 0, 'success'),
    (5, 1, 2, 'partial'),
    (0, 0, 2, 'error'),
])
def test_cleanup_completion_status_matrix(removed_files, removed_dirs, error_count, expected):
    status, message = ShellMaintenanceCommands._cleanup_completion({
        'removed_files': removed_files, 'removed_dirs': removed_dirs,
        'bytes_freed': 1024, 'error_count': error_count,
    })
    assert status == expected
    if expected == 'partial':
        assert 'partially completed' in message and '2 failed' in message


def test_clean_rejection_remains_failure_and_does_not_execute(monkeypatch):
    progress = []
    host = make_host(progress)
    service = FakeCleanupService()
    service.plan_data = {'items': [{
        'name': 'preview_temp', 'paths': [{'path': '/tmp/a'}],
        'scanned_paths': ['/tmp'], 'removed_files': 1, 'removed_dirs': 0,
        'bytes_freed': 1, 'errors': [], 'skipped_paths': [], 'prune_dirs': [],
    }]}
    def make_service(**kwargs):
        service.progress_callback = kwargs.get('progress_callback')
        return service
    monkeypatch.setattr(update_ops, 'ClientCleanupService', make_service)

    class Rejected:
        def __init__(self, owner):
            pass
        def select_preview_rows(self, *args, **kwargs):
            from client.runtime.execution.interaction_service import CommandInteractionError
            raise CommandInteractionError('Preview selection rejected, expired, or cancelled')

    monkeypatch.setattr('client.runtime.execution.interaction_service.CommandInteractions', Rejected)
    code, message = ShellMaintenanceCommands.clean(host, '')
    assert code == 0
    assert 'rejected' in message
    assert not service.executed
    assert progress[-1] == ('info', 'Waiting for cleanup approval...')


def test_clean_real_partial_delete_emits_grouped_progress_and_partial_wire_status(
        managed_cleanup, monkeypatch):
    from core.protocol.result_envelope import result_wire_event

    category = managed_cleanup / 'preview_temp'
    category.mkdir()
    good = category / 'good.tmp'
    denied = category / 'denied.tmp'
    good.write_bytes(b'good')
    denied.write_bytes(b'denied')
    monkeypatch.setattr(cleanup.ClientCleanupService, 'ITEMS', ('preview_temp',))

    original_remove = os.remove
    def remove(path, *args, **kwargs):
        if os.fspath(path) == str(denied):
            raise PermissionError('Permission denied')
        return original_remove(path, *args, **kwargs)
    monkeypatch.setattr(cleanup.os, 'remove', remove)

    progress = []
    host = make_host(progress)
    previews = []
    class Approve:
        def __init__(self, owner):
            pass
        def select_preview_rows(self, message, preview, *, title):
            previews.append(preview)
            return ['preview_temp']
    monkeypatch.setattr('client.runtime.execution.interaction_service.CommandInteractions', Approve)

    code, payload = ShellMaintenanceCommands.clean(host, '')

    assert code == 1
    assert payload['event_type'] == 'completed' and payload['status'] == 'partial'
    assert good.exists() is False and denied.exists() is True
    assert payload['message'].startswith('Cleanup partially completed: 1 files')
    wire = result_wire_event(91, code, payload)
    assert wire['event_type'] == 'completed' and wire['status'] == 'partial'
    assert sum(message.startswith('Scanned ') for _, message in progress) == 1
    assert progress[0] == ('info', 'Scanning cleanup directories...')
    assert progress[1][0] == 'info' and progress[1][1].startswith('Scanned preview_temp — ')
    assert progress[2] == ('info', 'Waiting for cleanup approval...')
    assert progress[3][0] == 'info' and progress[3][1].startswith('Cleaning preview_temp — ')
    assert progress[4] == ('warning', 'preview_temp: partially cleaned — 1 files, 0 directories deleted; 4.00B freed; 1 failed')
    assert progress[5] == ('error', f'Failed to delete: {denied}: Permission denied')
    assert len(previews) == 1 and 'row_details' not in previews[0]
    assert all('good.tmp' not in message for _, message in progress)


def test_directory_delete_failure_counts_entries_removed_before_permission_error(
        managed_cleanup, monkeypatch):
    category = managed_cleanup / 'preview_temp'
    category.mkdir()
    target = category / 'old-cache'
    target.mkdir()
    removed = target / 'removed.tmp'
    protected = target / 'protected.tmp'
    removed.write_bytes(b'gone')
    protected.write_bytes(b'stays')

    progress = []
    host = make_host(progress)
    service = cleanup.ClientCleanupService(
        progress_callback=lambda phase, item: ShellMaintenanceCommands._on_cleanup_progress(host, phase, item),
    )
    service.ITEMS = ('preview_temp',)
    plan = service.plan()
    real_rmtree = cleanup.shutil.rmtree

    def partial_rmtree(path, *args, **kwargs):
        if os.fspath(path) == str(target):
            os.remove(removed)
            raise PermissionError(13, 'Permission denied', str(protected))
        return real_rmtree(path, *args, **kwargs)
    monkeypatch.setattr(cleanup.shutil, 'rmtree', partial_rmtree)

    result = service.execute_plan(plan, {'preview_temp'})
    assert not removed.exists() and protected.exists() and target.exists()
    assert result['removed_files'] == 1
    assert result['removed_dirs'] == 0
    assert result['bytes_freed'] == 4
    assert result['error_count'] == 1
    assert ShellMaintenanceCommands._cleanup_completion(result)[0] == 'partial'
    error_lines = [message for level, message in progress if level == 'error']
    assert len(error_lines) == 1 and str(protected) in error_lines[0]
    assert str(removed) not in '\n'.join(error_lines)
