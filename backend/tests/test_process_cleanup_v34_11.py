"""v34.11 regressions: process matching/CLI parser and retained cleanup visibility."""
import json
import os
from types import SimpleNamespace

import pytest

from client.commands.common.mixins.process_ops import CommandProcessMixin
from client.commands.common.mixins.update_ops import CommandUpdateMixin
from client.commands.common.services.client_cleanup_service import ClientCleanupService
from client.commands.common.services.process import approved_process_service as processes
from client.commands.platform.specs.common import PS_ARGUMENT_SPEC
from client.commands.arguments.validator import ArgumentCommandValidator
from server.application.command.command_planner import CommandPlanner


def test_ps_has_generic_actions_flag_and_port_schema():
    opts = ArgumentCommandValidator().normalize(PS_ARGUMENT_SPEC,
        CommandPlanner.__new__(CommandPlanner).parse_argument_command(
            'acmd ps --port 8080 --json --with-actions')['args'])
    assert opts['port'] == 8080
    assert opts['json'] is True
    assert opts['with-actions'] is True


def test_ps_available_on_all_platforms():
    from client.commands.platform.mac import MacCommands
    from client.commands.platform.win import WindowsCommands
    from client.commands.platform.linux import LinuxCommands
    from client.commands.platform.ios import iOSCommands
    for cls in (MacCommands, WindowsCommands, LinuxCommands, iOSCommands):
        assert cls._acmd_ps.argument_command_name == 'ps'


def test_no_imposed_protected_pid_list_at_signalling(monkeypatch):
    # Fake psutil, no actual OS process is signalled.
    import psutil
    called = []
    class FakeProcess:
        def create_time(self): return 123.0
        def name(self): return 'example'
        def exe(self): return '/example'
        def terminate(self): called.append('term')
        def kill(self): called.append('kill')
    monkeypatch.setattr(psutil, 'Process', lambda pid: FakeProcess())
    row = {'pid': 1, 'created_at': 123.0, 'name': 'example', 'exec_path': '/example'}
    assert processes.terminate_verified(row, force=False) == 'SIGTERM'
    assert called == ['term']


def test_clean_returns_all_empty_categories_with_scanned_directories(monkeypatch):
    def mocked_plan(self):
        return {'items': [
            {'name': name, 'paths': [], 'prune_dirs': [],
             'scanned_paths': [f'/test/root/{name}']}
            for name in ClientCleanupService.ITEMS
        ]}
    monkeypatch.setattr(ClientCleanupService, 'plan', mocked_plan)
    monkeypatch.setattr(ClientCleanupService, 'execute_plan',
                        lambda *args: pytest.fail('No deletion when nothing to clean'))
    host = SimpleNamespace(_set_timeout=lambda *_: None, _checkpoint=lambda **kw: None,
                           _get_current_bundle_release_dir=lambda *_: '')
    status, output = CommandUpdateMixin.clean(host, '')
    assert status == 1
    for category in ClientCleanupService.ITEMS:
        assert f'[{category}]' in output
        assert f'/test/root/{category}' in output
    assert output.count('(empty)') == len(ClientCleanupService.ITEMS)
    assert 'Nothing to clean' in output


def test_original_managed_empty_category_can_be_pruned_with_selected_plan(tmp_path, monkeypatch):
    import client.commands.common.services.client_cleanup_service as module
    root = tmp_path / 'rch_tmp'
    category = root / 'preview_temp'
    category.mkdir(parents=True)
    monkeypatch.setattr(module, 'get_client_temp_root', lambda **kw: str(root))
    monkeypatch.setattr(module, 'get_temp_category_dir',
                        lambda name, **kw: str(root / name))
    monkeypatch.setattr(module.tempfile, 'gettempdir', lambda: str(tmp_path))
    service = ClientCleanupService()
    service.ITEMS = ('preview_temp',)
    plan = service.plan()
    assert category.exists()
    item = plan['items'][0]
    assert item['paths'] == []
    assert str(category) in item['prune_dirs']
    assert str(category) in item['scanned_paths']
    result = service.execute_plan(plan, {'preview_temp'})
    assert not category.exists()
    assert result['error_count'] == 0
