"""Capabilities are declared from code and disabled modules stay unimported."""

import os
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from client.config import feature_config
from client.commands.runtime.catalog import CommandCatalog
from core.utils.decorator import desc, confirm
from client.commands.runtime.interrupts import timeout, cancel_policy
from client.commands.runtime.manifest_metadata import command_metadata


@pytest.mark.parametrize('os_alias,screen_view,pty,clipboard', [
    ('mac', True, True, True),
    ('win', True, True, True),
    ('linux', False, True, False),
    ('ios', False, False, True),
])
def test_platform_defaults(monkeypatch, os_alias, screen_view, pty, clipboard):
    result = feature_config.resolve_features(os_alias, overrides={})
    assert result['screen_view'] is screen_view
    assert result['pty'] is pty
    assert result['clipboard'] is clipboard
    assert result['screen_input'] is screen_view



def test_external_tool_and_process_monitor_platform_features():
    for platform in ('mac', 'win', 'linux'):
        assert feature_config.resolve_features(platform, {})['external_tool'] is True
        assert feature_config.resolve_features(platform, {})['process_monitor'] is True
    assert feature_config.resolve_features('ios', {'external_tool': True, 'process_monitor': True})['external_tool'] is False
    assert feature_config.resolve_features('ios', {'external_tool': True, 'process_monitor': True})['process_monitor'] is False
    disabled = feature_config.resolve_features('mac', {'external_tool': False, 'process_monitor': False})
    assert disabled['external_tool'] is False
    assert disabled['process_monitor'] is False
    assert disabled['pty'] is True  # Independent core capability


def test_features_validate_user_overrides(monkeypatch):
    selected = feature_config.resolve_features('mac', {
        'screen_view': False, 'screen_input': True, 'pty': False,
    })
    assert selected['screen_view'] is False
    assert selected['screen_input'] is False
    assert selected['pty'] is False
    with pytest.raises(ValueError, match='Unknown Client feature'):
        feature_config.resolve_features('mac', {'unknown': False})
    with pytest.raises(ValueError, match='must be boolean'):
        feature_config.resolve_features('mac', {'pty': 'false'})


def test_watchdog_single_capability_independent_of_set(monkeypatch):
    from client.config import runtime_config
    for alias in ('mac', 'win', 'linux'):
        for is_enabled in (False, True):
            monkeypatch.setattr(runtime_config, 'PROCESS_RECOVERY_WATCHDOG_ENABLED', is_enabled)
            monkeypatch.setattr(runtime_config, 'LOCAL_HEARTBEAT_WATCHDOG_ENABLED', is_enabled)
            monkeypatch.setattr(runtime_config, 'REMOTE_CONTROL_WATCHDOG_ENABLED', is_enabled)
            assert feature_config.resolve_features(alias, {})['watchdog'] is True
    assert feature_config.resolve_features('ios', {'watchdog': True})['watchdog'] is False
    assert feature_config.resolve_features('mac', {'watchdog': False})['watchdog'] is False
    with pytest.raises(ValueError, match='Unknown Client feature'):
        feature_config.resolve_features('mac', {'remote_control_watchdog': False})


def test_launchd_capability_is_loaded(monkeypatch):
    from client.runtime.launch_context import LAUNCH_MODE_ENV, LAUNCH_SOURCE_ENV
    monkeypatch.setenv(LAUNCH_MODE_ENV, 'user_service')
    monkeypatch.setenv(LAUNCH_SOURCE_ENV, 'launchagent')
    assert feature_config.resolve_features('mac', {})['watchdog'] is True


def test_command_declared_metadata_and_confirm_semantics():
    @desc('A command', group='example', output='stream')
    @timeout(11)
    @cancel_policy('cooperative')
    @confirm('Approve?')
    def sample(_owner):
        return 1, 'ok'

    metadata = command_metadata(sample)
    assert metadata == {
        'kind': 'command', 'source': 'client',
        'cancel_policy': 'cooperative', 'timeout': 11,
        'confirmation': True,
        'interaction': {'may_request': True},
        'output': 'stream',
    }


def test_linux_command_manifest_is_unique_and_complete():
    catalog = CommandCatalog(SimpleNamespace())
    catalog._get_platform_name = lambda: 'linux'
    entries = catalog.get_commands().get_command_manifest_payload()
    names = [item['name'] for item in entries]
    assert len(names) == len(set(names))
    required = {
        'name', 'kind', 'source', 'help', 'group', 'suggest',
        'cancel_policy', 'timeout', 'interaction', 'output',
    }
    assert all(required <= set(item) for item in entries)
    assert all(item['source'] == 'client' for item in entries)
    assert any(item['kind'] == 'acmd' for item in entries)
    modes = {item['name']: item['output'] for item in entries}
    assert modes['shell_stream'] == 'stream'
    assert modes['pyexec_stream'] == 'stream'
    assert modes['pyexec'] == 'collect'
    policies = {item['name']: item['cancel_policy'] for item in entries}
    assert set(policies.values()) <= {'none', 'cooperative', 'process'}
    for name in ('pyexec', 'pyexec_stream', 'download'):
        assert policies[name] == 'cooperative'
    assert all(item['suggest'] is True for item in entries)
    assert not any('template' in item or 'streaming' in item for item in entries)
    assert any(item.get('confirmation') is True for item in entries)
    assert not any(item.get('confirmation') is False for item in entries)


def test_no_disabled_manager_imports_in_fresh_client():
    script = textwrap.dedent('''
        from client.config import feature_config
        feature_config.FEATURE_OVERRIDES.update({
            'pty': False, 'screen_view': False, 'screen_input': False,
            'clipboard': False, 'watchdog': False,
        })
        from client.bootstrap.client_app import Client
        import sys
        client = Client(('127.0.0.1', 1))
        runtime = client.server.runtime
        assert runtime.pty_manager is None
        assert runtime.screen_view_manager is None
        assert runtime.clipboard_manager is None
        assert client.watchdog_manager is None
        assert client.process_recovery_watchdog_manager is None
        optional = [
            'client.pty.manager', 'client.screen.manager',
            'client.clipboard.manager', 'client.watchdog.client_watchdog_manager',
            'client.watchdog.watchdog_process', 'client.watchdog.process_recovery_watchdog',
            'client.watchdog.local_heartbeat_watchdog', 'client.watchdog.remote_control_watchdog',
        ]
        assert not [name for name in optional if name in sys.modules]
        manifest = runtime.command_executor.get_commands().get_command_manifest_payload()
        assert manifest and not [name for name in optional if name in sys.modules]
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_disabled_screen_input_is_rejected_even_with_read_only_view():
    from client.connection.message_router import ClientInboundMessageRouter

    messages = []

    class ScreenManager:
        def handle_input(self, *_args, **_kwargs):
            raise AssertionError('screen input handler must not be called')

    connection = SimpleNamespace(
        runtime=SimpleNamespace(features={'screen_input': False}, screen_view_manager=ScreenManager()),
        send=messages.append,
    )
    router = ClientInboundMessageRouter(connection)
    assert router.handle_screen_input_message({'screen_session_id': 'sample', 'event': {'action': 'move'}}) is None
    assert messages[0]['type'] == 'screen_input_error'
    assert messages[0]['screen_session_id'] == 'sample'


def test_supported_watchdog_imports_implementation_with_all_modes_off():
    script = textwrap.dedent("""
        import sys
        from client.config import feature_config, runtime_config
        from client.watchdog import watchdog_status
        runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED = False
        runtime_config.LOCAL_HEARTBEAT_WATCHDOG_ENABLED = False
        runtime_config.PROCESS_RECOVERY_WATCHDOG_ENABLED = False
        feature_config.FEATURE_OVERRIDES.update({'watchdog': True, 'pty': False, 'screen_view': False, 'clipboard': False})
        from client.bootstrap.client_app import Client
        client = Client(('127.0.0.1', 1))
        assert client.watchdog_manager is not None
        assert client.watchdog_manager._watchdog_process is None
        assert client.process_recovery_watchdog_manager is None  # Process manager lives in rchclient.main
        assert {'client.watchdog.watchdog_process', 'client.watchdog.remote_control_watchdog',
                'client.watchdog.local_heartbeat_watchdog'} <= set(sys.modules)
        assert client.features['watchdog'] is True
    """)
    result = subprocess.run([sys.executable, '-c', script], cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_set_watchdog_modes_hot_start_and_stop_without_changing_capability(monkeypatch):
    from client.config import runtime_config
    from client.commands.common.mixins.runtime_config_ops import CommandRuntimeConfigMixin

    class Guard:
        def __init__(self):
            self.calls = []
        def stop(self): self.calls.append('stop')
        def start(self): self.calls.append('start')

    class Process:
        def __init__(self): self.calls = []
        def start(self): self.calls.append('start')
        def stop(self): self.calls.append('stop')

    guard, process = Guard(), Process()
    owner = CommandRuntimeConfigMixin()
    owner._checkpoint = lambda: None
    owner.socket = SimpleNamespace(
        runtime=SimpleNamespace(features={'watchdog': True}),
        watchdog_manager=guard, process_recovery_watchdog_manager=process,
    )
    monkeypatch.setattr('client.commands.common.mixins.runtime_config_ops.is_launchd_managed_client', lambda: False)
    monkeypatch.setattr(runtime_config, 'REMOTE_CONTROL_WATCHDOG_ENABLED', True)
    result = owner._apply_runtime_config_side_effects('REMOTE_CONTROL_WATCHDOG_ENABLED', True)
    assert guard.calls == ['stop', 'start']
    assert result and 'Applied' in ''.join(result)
    monkeypatch.setattr(runtime_config, 'PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
    owner._apply_runtime_config_side_effects('PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
    assert process.calls == ['start']
    owner._apply_runtime_config_side_effects('PROCESS_RECOVERY_WATCHDOG_ENABLED', False)
    assert process.calls[-1] == 'stop'
    assert owner.socket.runtime.features['watchdog'] is True

    # A disabled capability can retain user preferences without creating managers.
    owner.socket = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': False}),
                                   watchdog_manager=None, process_recovery_watchdog_manager=None)
    result = owner._apply_runtime_config_side_effects('PROCESS_RECOVERY_WATCHDOG_ENABLED', True)
    assert 'unavailable' in ''.join(result)
    result = owner._apply_runtime_config_side_effects('LOCAL_HEARTBEAT_WATCHDOG_ENABLED', True)
    assert 'unavailable' in ''.join(result)
