"""Regression coverage for command metadata and Windows Client behavior."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from client.commands.runtime.catalog import CommandCatalog
from core.utils.decorator import confirm


def test_manifest_keeps_only_suggested_names_and_output_contract():
    catalog = CommandCatalog(SimpleNamespace())
    catalog._get_platform_name = lambda: 'win'
    entries = catalog.get_commands().get_command_manifest_payload()
    by_name = {item['name']: item for item in entries}
    assert all(item['suggest'] for item in entries)
    assert 'browse_dir' not in by_name
    assert 'receive_file' not in by_name
    assert not any('template' in item or 'streaming' in item for item in entries)
    assert by_name['screenshot']['output'] == 'stream'
    assert by_name['update']['output'] == 'stream'
    assert by_name['shell']['output'] == 'collect'
    assert by_name['acmd help']['name'] == 'acmd help'


def test_mac_progressive_command_contract():
    catalog = CommandCatalog(SimpleNamespace())
    catalog._get_platform_name = lambda: 'mac'
    by_name = {item['name']: item for item in catalog.get_commands().get_command_manifest_payload()}
    for name in ('screenshot', 'webcam_snap', 'file_shred', 'update'):
        assert by_name[name]['output'] == 'stream'
    assert by_name['relaunch_instance']['confirmation'] is True


def test_confirm_bypass_allows_relaunch_without_requesting_interaction():
    from client.commands.common.mixins.session_ops import CommandSessionMixin
    owner = CommandSessionMixin()
    owner.socket = object()
    with patch('client.commands.common.mixins.session_ops.reset') as reset, \
         patch('client.commands.common.services.interaction_service.CommandInteractions.confirm',
               side_effect=AssertionError('should not request confirmation')):
        owner.relaunch_instance('--no-confirm')
    reset.assert_called_once_with(owner.socket)


def test_confirm_default_requests_interaction_without_bypass():
    @confirm('Proceed?')
    def command(owner, options=''):
        return 1, options
    with patch('client.commands.common.services.interaction_service.CommandInteractions.confirm', return_value=True) as ask:
        assert command(SimpleNamespace(), 'hello') == (1, 'hello')
        ask.assert_called_once()
    with patch('client.commands.common.services.interaction_service.CommandInteractions.confirm',
               side_effect=AssertionError('unexpected dialog')):
        assert command(SimpleNamespace(), '--no-confirm') == (1, '')


def test_approved_process_inspection_supports_older_psutil(monkeypatch):
    from client.commands.common.services.process import approved_process_service as svc
    class DummyProcess:
        pid = 733
        def oneshot(self):
            from contextlib import nullcontext
            return nullcontext()
        def create_time(self): return 2.5
        def name(self): return 'test'
        def username(self): return 'user'
        def exe(self): return '/bin/test'
        def cmdline(self): return ['test']
        def cwd(self): return '/'
        def ppid(self): return 1
        def status(self): return 'running'
        def memory_info(self): return SimpleNamespace(rss=20)
        def num_threads(self): return 2
        def connections(self, kind):
            assert kind == 'inet'
            return []
    import psutil
    monkeypatch.setattr(psutil, 'Process', lambda _pid: DummyProcess())
    assert svc.inspect_process(733)['listening'] == []


def test_shell_failure_preserves_stdout_and_exit_status():
    from client.commands.common.mixins.execution_ops import CommandExecutionMixin
    owner = CommandExecutionMixin()
    owner._run_shell_command = lambda _command: SimpleNamespace(returncode=1, stdout='WRITE DENIED: temp\n', stderr='PowerShell error\n')
    result = owner.shell('test')
    assert result[0] == 0
    assert 'WRITE DENIED' in result[1]
    assert 'PowerShell error' in result[1]
    assert 'code 1' in result[1]


def test_windows_watchdog_stop_has_bounded_taskkill(monkeypatch):
    from client.watchdog import watchdog_process
    process = Mock(pid=733)
    process.poll.return_value = None
    manager = watchdog_process.ClientWatchdogProcess.__new__(watchdog_process.ClientWatchdogProcess)
    manager._process = process
    monkeypatch.setattr(watchdog_process.os, 'name', 'nt')
    with patch.object(watchdog_process.subprocess, 'run') as run:
        manager.stop()
        assert run.call_args.kwargs['timeout'] == 5


def test_server_candidates_use_single_name_contract():
    from server.application.web.command_catalog_api import WebCommandCatalogApi
    api = WebCommandCatalogApi(server=SimpleNamespace(), command_executor_factory=Mock())
    session = SimpleNamespace(session_info=SimpleNamespace(command_manifest=[
        {'name': 'acmd help', 'source': 'client', 'suggest': True, 'output': 'collect'},
        {'name': 'screenshot', 'source': 'client', 'suggest': True, 'output': 'stream'},
    ]))
    candidates = api._get_client_command_candidates(session)
    assert [item['name'] for item in candidates] == ['acmd help', 'screenshot']
    assert all('template' not in item for item in candidates)
    assert not any('streaming' in item or 'required' in item.get('confirmation', {})
                   for item in candidates)


def test_watchdog_start_failure_reports_saved_but_not_running(monkeypatch):
    from client.commands.common.mixins.runtime_config_ops import CommandRuntimeConfigMixin
    from client.config import runtime_config
    owner = CommandRuntimeConfigMixin()
    owner._checkpoint = lambda: None
    supervisor = Mock()
    supervisor.start.side_effect = RuntimeError('access denied')
    owner.socket = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': True}),
                                   process_recovery_watchdog_manager=supervisor, watchdog_manager=Mock())
    monkeypatch.setattr(runtime_config, 'REMOTE_CONTROL_WATCHDOG_ENABLED', False)
    monkeypatch.setattr(runtime_config, 'LOCAL_HEARTBEAT_WATCHDOG_ENABLED', False)
    monkeypatch.setattr('client.commands.common.mixins.runtime_config_ops.is_launchd_managed_client', lambda: False)
    messages = owner._apply_runtime_config_side_effects('PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
    assert any('Saved' in message and 'access denied' in message for message in messages)
    owner.socket.watchdog_manager.stop.assert_not_called()


def test_agent_bundle_injection_without_revision_parts(tmp_path):
    from server.application.agent.agent_build_utils import inject_python_client_config
    config_dir = tmp_path / 'client' / 'config'
    config_dir.mkdir(parents=True)
    with patch('server.application.agent.agent_build_utils.build_client_revision_manifest',
               return_value={'revision': 'rev123', 'files': {'client/test.py': 'abc'}}) as builder:
        inject_python_client_config(str(tmp_path), str(tmp_path), '127.0.0.1', 9999, 8085,
                                    'build-test')
    builder.assert_called_once_with(str(tmp_path))
    generated = (config_dir / 'config.py').read_text(encoding='utf-8')
    assert 'CLIENT_SOURCE_REVISION = "rev123"' in generated
    assert 'CLIENT_SOURCE_REVISION_FILES =' in generated
    assert 'CLIENT_SOURCE_REVISION_PARTS' not in generated
