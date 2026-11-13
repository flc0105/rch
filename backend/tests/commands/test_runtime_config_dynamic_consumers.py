"""Runtime config values are read on use; side effects are explicit and registered."""

import json
import sys
import types
from types import SimpleNamespace

import pytest

from client.config import runtime_config
from client.config.runtime_config_service import RuntimeConfigService
from client.config.runtime_config_effects import RuntimeConfigEffects


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNTIME_CONFIG_PATH', str(tmp_path / 'runtime_config.json'))
    for key in runtime_config._RUNTIME_CONFIG_DEFAULTS:
        monkeypatch.setattr(runtime_config, key, getattr(runtime_config, key))
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_KEYS', list(runtime_config._RUNTIME_CONFIG_OVERRIDE_KEYS))
    monkeypatch.setattr(runtime_config, '_RUNTIME_CONFIG_OVERRIDE_PATH', runtime_config._RUNTIME_CONFIG_OVERRIDE_PATH)
    return tmp_path / 'runtime_config.json'


def test_prune_redundant_overrides_still_removes_default_only(isolated_config):
    from client.config.runtime_config_store import load_runtime_overrides, save_runtime_overrides

    save_runtime_overrides({
        'COMMAND_DEFAULT_SHELL_TIMEOUT': runtime_config._RUNTIME_CONFIG_DEFAULTS['COMMAND_DEFAULT_SHELL_TIMEOUT'],
        'COMMAND_DEFAULT_STREAM_TIMEOUT': 9,
    })
    service = RuntimeConfigService()
    assert service.prune_redundant_overrides() == ['COMMAND_DEFAULT_SHELL_TIMEOUT']
    assert load_runtime_overrides() == {'COMMAND_DEFAULT_STREAM_TIMEOUT': 9}


def test_new_defaults_and_strategy_enums(isolated_config):
    assert runtime_config._RUNTIME_CONFIG_DEFAULTS['HTTP_TRANSFER_MODE'] == 'cancelable'
    assert runtime_config._RUNTIME_CONFIG_DEFAULTS['SCREEN_FRAME_STRATEGY'] == 'keyframe_delta'
    svc = RuntimeConfigService(features={'screen_view': True})
    assert svc.get_config_meta('HTTP_TRANSFER_MODE')['choices'] == ['legacy', 'cancelable']
    assert svc.get_config_meta('SCREEN_FRAME_STRATEGY')['choices'] == ['full_jpeg', 'keyframe_delta']


def test_set_reset_reset_all_changes_next_transfer_and_python_strategy(isolated_config):
    from client.runtime.http_transfer.http_file_transfer_service import HttpFileTransferService
    from client.runtime.execution.python_execution.factory import get_python_execution_mode
    from client.runtime.http_transfer.strategies.cancelable import CancelableHttpTransferStrategy
    from client.runtime.http_transfer.strategies.legacy import LegacyHttpTransferStrategy
    from client.transfers.manager import _TransferTaskOwner
    from client.runtime.execution.context import ExecutionContext

    svc = RuntimeConfigService(features={'screen_view': True})
    owner = SimpleNamespace()
    transfer = HttpFileTransferService(owner)
    assert isinstance(transfer.get_transfer_strategy(), CancelableHttpTransferStrategy)
    assert get_python_execution_mode() == 'inproc'

    svc.set_config_value('HTTP_TRANSFER_MODE', 'legacy')
    assert isinstance(transfer.get_transfer_strategy(), LegacyHttpTransferStrategy)
    # An independent transfer owner created in the old mode must not carry a snapshot.
    independent_owner = _TransferTaskOwner(SimpleNamespace(), ExecutionContext(command_id='test'))
    assert isinstance(HttpFileTransferService(independent_owner).get_transfer_strategy(), LegacyHttpTransferStrategy)

    svc.set_config_value('SCRIPT_DEFAULT_EXECUTION_MODE', 'subprocess_pipe')
    assert get_python_execution_mode() == 'subprocess_pipe'
    svc.set_config_value('SCREEN_FRAME_STRATEGY', 'full_jpeg')
    saved = json.loads(isolated_config.read_text(encoding='utf-8'))
    assert saved['HTTP_TRANSFER_MODE'] == 'legacy'
    assert saved['SCRIPT_DEFAULT_EXECUTION_MODE'] == 'subprocess_pipe'
    assert saved['SCREEN_FRAME_STRATEGY'] == 'full_jpeg'

    svc.reset_config_key('HTTP_TRANSFER_MODE')
    assert isinstance(transfer.get_transfer_strategy(), CancelableHttpTransferStrategy)
    assert 'HTTP_TRANSFER_MODE' not in json.loads(isolated_config.read_text(encoding='utf-8'))
    svc.reset_all_overrides()
    assert not isolated_config.exists()
    assert get_python_execution_mode() == 'inproc'
    assert runtime_config.SCREEN_FRAME_STRATEGY == 'keyframe_delta'


def test_dynamic_timeout_and_reconnect_read_in_same_process(isolated_config):
    from client.runtime.execution.scope import ExecutionRuntimeMixin
    from client.commands.common.mixins.execution_ops import CommandExecutionMixin
    from client.bootstrap.client_app import Client

    svc = RuntimeConfigService()
    executor = object.__new__(CommandExecutionMixin)
    client = object.__new__(Client)
    fallback = ExecutionRuntimeMixin()
    fallback.execution_context = None
    assert executor.DEFAULT_SHELL_TIMEOUT == 30
    assert executor.DEFAULT_STREAM_TIMEOUT == 300
    assert client.RECONNECT_INTERVAL == 5
    assert fallback._resolve_command_fallback_timeout() is None
    svc.set_config_value('COMMAND_DEFAULT_SHELL_TIMEOUT', '7')
    svc.set_config_value('COMMAND_DEFAULT_STREAM_TIMEOUT', '9')
    svc.set_config_value('RECONNECT_INTERVAL_SECONDS', '3')
    assert (executor.DEFAULT_SHELL_TIMEOUT, executor.DEFAULT_STREAM_TIMEOUT, client.RECONNECT_INTERVAL) == (7, 9, 3)
    # Explicit timeout always takes precedence.
    assert fallback._resolve_command_fallback_timeout(123) == 123
    svc.reset_all_overrides()
    assert (executor.DEFAULT_SHELL_TIMEOUT, executor.DEFAULT_STREAM_TIMEOUT, client.RECONNECT_INTERVAL) == (30, 300, 5)


def test_inbound_timeout_runtime_config_is_persisted_and_reset(isolated_config):
    service = RuntimeConfigService()
    key = 'SERVER_INBOUND_TIMEOUT_SECONDS'
    assert runtime_config._RUNTIME_CONFIG_DEFAULTS[key] == 120
    meta = service.get_config_meta(key)
    assert meta['group'] == 'connection'
    assert meta['min'] == 0
    assert service.is_supported_key(key)
    assert (service.get_value_type(runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS),
            runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS) == ('integer', 120)

    result = service.set_config_value(key, '0')
    assert (result.new_value, result.source) == (0, 'override')
    assert runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS == 0
    assert json.loads(isolated_config.read_text(encoding='utf-8'))[key] == 0
    assert next(item for item in service.build_config_payload()['items'] if item['key'] == key)['value'] == 0

    with pytest.raises(ValueError, match='must be >= 0'):
        service.set_config_value(key, '-1')
    with pytest.raises(ValueError, match='Invalid integer'):
        service.set_config_value(key, 'invalid')
    assert runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS == 0

    reset = service.reset_config_key(key)
    assert (reset.new_value, reset.source) == (120, 'default')
    assert runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS == 120
    assert not isolated_config.exists()


def test_set_command_updates_inbound_timeout_on_current_client(isolated_config):
    from client.commands.common.mixins.runtime_config_ops import CommandRuntimeConfigMixin

    owner = CommandRuntimeConfigMixin()
    owner.socket = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': False}))
    owner._checkpoint = lambda: None

    status, message = owner.set('SERVER_INBOUND_TIMEOUT_SECONDS 0')
    assert status == 1, message
    assert message == '[+] SERVER_INBOUND_TIMEOUT_SECONDS updated, value: 120 → 0'
    assert runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS == 0
    assert json.loads(isolated_config.read_text(encoding='utf-8'))['SERVER_INBOUND_TIMEOUT_SECONDS'] == 0

    status, message = owner.set('--reset SERVER_INBOUND_TIMEOUT_SECONDS')
    assert status == 1, message
    assert runtime_config.SERVER_INBOUND_TIMEOUT_SECONDS == 120
    assert not isolated_config.exists()


def test_set_command_compact_script_mode_output(isolated_config):
    from client.commands.common.mixins.runtime_config_ops import CommandRuntimeConfigMixin

    owner = CommandRuntimeConfigMixin()
    owner.socket = SimpleNamespace(runtime=SimpleNamespace(features={}))
    owner._checkpoint = lambda: None
    runtime_config.SCRIPT_DEFAULT_EXECUTION_MODE = 'inproc'
    assert owner.set('SCRIPT_DEFAULT_EXECUTION_MODE subprocess_pipe') == (
        1, "[+] SCRIPT_DEFAULT_EXECUTION_MODE updated, value: 'inproc' → 'subprocess_pipe'")
    assert owner.set('SCRIPT_DEFAULT_EXECUTION_MODE inproc') == (
        1, "[+] SCRIPT_DEFAULT_EXECUTION_MODE updated, value: 'subprocess_pipe' → 'inproc'")


def test_writes_never_reflect_into_unrelated_loaded_modules(isolated_config, monkeypatch):
    svc = RuntimeConfigService()
    ghost = types.ModuleType('client.runtime.unrelated_config')
    ghost.HTTP_TRANSFER_MODE = 'cancelable'
    class Ghost:
        HTTP_TRANSFER_MODE = 'cancelable'
    ghost.Ghost = Ghost
    monkeypatch.setitem(sys.modules, ghost.__name__, ghost)
    svc.set_config_value('HTTP_TRANSFER_MODE', 'legacy')
    assert ghost.HTTP_TRANSFER_MODE == 'cancelable'
    assert Ghost.HTTP_TRANSFER_MODE == 'cancelable'
    assert runtime_config.HTTP_TRANSFER_MODE == 'legacy'


def test_store_write_error_keeps_in_process_value(isolated_config, monkeypatch):
    import client.config.runtime_config_service as module
    svc = RuntimeConfigService()
    def failure(*_args):
        raise OSError('write denied')
    monkeypatch.setattr(module, 'update_runtime_override', failure)
    with pytest.raises(OSError, match='write denied'):
        svc.set_config_value('HTTP_TRANSFER_MODE', 'legacy')
    assert runtime_config.HTTP_TRANSFER_MODE == 'cancelable'


def test_change_hooks_register_only_active_lifecycle_effects():
    owner = SimpleNamespace(socket=None)
    hooks = RuntimeConfigEffects(owner.socket, is_launchd_managed_client=lambda: False)
    assert set(hooks._callbacks) == {
        'SCREEN_FRAME_STRATEGY', 'PROCESS_RECOVERY_WATCHDOG_ENABLED',
        *RuntimeConfigEffects.WATCHDOG_CONFIG_KEYS,
    }
    assert hooks.apply('HTTP_TRANSFER_MODE', 'legacy') == []
    assert 'new Screen View' in ''.join(hooks.apply('SCREEN_FRAME_STRATEGY', 'full_jpeg'))


def test_set_command_watchdog_callback_immediate_and_reset(isolated_config, monkeypatch):
    import client.commands.common.mixins.runtime_config_ops as ops
    from client.commands.common.mixins.runtime_config_ops import CommandRuntimeConfigMixin

    events = []
    watcher = SimpleNamespace(start=lambda: events.append('start'), stop=lambda: events.append('stop'))
    owner = CommandRuntimeConfigMixin()
    owner._checkpoint = lambda: None
    owner.socket = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': True, 'screen_view': True}),
                                   watchdog_manager=watcher, process_recovery_watchdog_manager=None)
    monkeypatch.setattr(ops, 'is_launchd_managed_client', lambda: False)
    status, message = owner.set('REMOTE_CONTROL_WATCHDOG_ENABLED true')
    assert status == 1, message
    assert events == ['stop', 'start']
    assert runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED is True
    assert json.loads(isolated_config.read_text(encoding='utf-8'))['REMOTE_CONTROL_WATCHDOG_ENABLED'] is True
    status, message = owner.set('--reset REMOTE_CONTROL_WATCHDOG_ENABLED')
    assert status == 1, message
    assert events == ['stop', 'start', 'stop', 'start']
    assert runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED is False


def test_reset_all_triggers_callbacks_and_restores_defaults(isolated_config, monkeypatch):
    import client.commands.common.mixins.runtime_config_ops as ops
    from client.commands.common.mixins.runtime_config_ops import CommandRuntimeConfigMixin

    events = []
    watcher = SimpleNamespace(start=lambda: events.append('start'), stop=lambda: events.append('stop'))
    owner = CommandRuntimeConfigMixin()
    owner._checkpoint = lambda: None
    owner.socket = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': True, 'screen_view': True}),
                                   watchdog_manager=watcher, process_recovery_watchdog_manager=None)
    monkeypatch.setattr(ops, 'is_launchd_managed_client', lambda: False)
    assert owner.set('HTTP_TRANSFER_MODE legacy')[0] == 1
    assert owner.set('SCREEN_FRAME_STRATEGY full_jpeg')[0] == 1
    assert owner.set('REMOTE_CONTROL_WATCHDOG_ENABLED true')[0] == 1
    assert owner.set('--reset-all')[0] == 1
    assert not isolated_config.exists()
    assert runtime_config.HTTP_TRANSFER_MODE == 'cancelable'
    assert runtime_config.SCREEN_FRAME_STRATEGY == 'keyframe_delta'
    assert runtime_config.REMOTE_CONTROL_WATCHDOG_ENABLED is False
    assert len(events) >= 4


def test_buffer_preview_and_new_screen_sessions_use_latest_values(isolated_config):
    from client.runtime.http_transfer.strategies.cancelable import CancelableHttpTransferStrategy
    from client.runtime.filesystem.preview_image_service import PreviewImageService
    from client.screen.frame_strategies.factory import build_screen_frame_strategy
    from client.screen.frame_strategies.full_jpeg import FullJpegFrameStrategy
    from client.screen.frame_strategies.keyframe_delta import KeyframeDeltaFrameStrategy

    svc = RuntimeConfigService(features={'screen_view': True})
    strategy = CancelableHttpTransferStrategy(SimpleNamespace())
    preview = PreviewImageService()
    assert strategy.get_buffer_size() == 1048576
    assert preview.is_enabled() is False
    assert preview.get_configured_quality() == 75
    assert isinstance(build_screen_frame_strategy(), KeyframeDeltaFrameStrategy)
    svc.set_config_value('HTTP_TRANSFER_BUFFER_SIZE', '65536')
    svc.set_config_value('PREVIEW_IMAGE_COMPRESS_ENABLED', 'true')
    svc.set_config_value('PREVIEW_IMAGE_COMPRESS_QUALITY', '45')
    svc.set_config_value('SCREEN_FRAME_STRATEGY', 'full_jpeg')
    assert strategy.get_buffer_size() == 65536
    assert preview.is_enabled() is True
    assert preview.get_configured_quality() == 45
    assert isinstance(build_screen_frame_strategy(), FullJpegFrameStrategy)
    svc.reset_all_overrides()
    assert strategy.get_buffer_size() == 1048576
    assert preview.is_enabled() is False
    assert preview.get_configured_quality() == 75
    assert isinstance(build_screen_frame_strategy(), KeyframeDeltaFrameStrategy)


def test_handshake_builder_reports_latest_runtime_values(isolated_config):
    from client.runtime.client_info_builder import ClientInfoBuilder
    svc = RuntimeConfigService()
    builder = ClientInfoBuilder('test')
    info = builder.build()
    assert (info['http_transfer_mode'], info['script_default_execution_mode']) == ('cancelable', 'inproc')
    svc.set_config_value('HTTP_TRANSFER_MODE', 'legacy')
    svc.set_config_value('SCRIPT_DEFAULT_EXECUTION_MODE', 'subprocess_pipe')
    info = builder.build()
    assert (info['http_transfer_mode'], info['script_default_execution_mode']) == ('legacy', 'subprocess_pipe')
    svc.reset_all_overrides()
    info = builder.build()
    assert (info['http_transfer_mode'], info['script_default_execution_mode']) == ('cancelable', 'inproc')
