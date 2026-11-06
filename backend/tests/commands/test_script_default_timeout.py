"""Script timeout is independent from shell streaming timeout."""

import pytest

from client.config import runtime_config
from client.commands.common.mixins.execution_ops import CommandExecutionMixin
from client.commands.base import CommandRuntimeMixin
from client.commands.common.services.runtime.runtime_config_service import RuntimeConfigService
from client.commands.runtime.context import CommandExecutionContext


@pytest.fixture
def script_settings(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNTIME_CONFIG_PATH', str(tmp_path / 'runtime_config.json'))
    monkeypatch.setattr(runtime_config, 'SCRIPT_DEFAULT_TIMEOUT', 300)
    monkeypatch.setattr(runtime_config, 'COMMAND_DEFAULT_STREAM_TIMEOUT', 300)
    return RuntimeConfigService()


def test_script_timeout_in_config_payload_and_persistence(script_settings, tmp_path):
    service = script_settings
    keys = {item['key']: item for item in service.build_config_payload()['items']}
    assert keys['SCRIPT_DEFAULT_TIMEOUT']['default_value'] == 300
    assert keys['SCRIPT_DEFAULT_TIMEOUT']['group'] == 'script'
    ordered = [item['key'] for item in service.build_config_payload()['items']]
    assert ordered.index('SCRIPT_DEFAULT_TIMEOUT') == ordered.index('COMMAND_DEFAULT_STREAM_TIMEOUT') + 1
    # The client declares display order; the UI consumes the returned list unchanged.
    declared = [
        key for key in service._iter_runtime_config_keys()
        if service.is_exposed_key(key) and service._feature_available(key)
    ]
    assert ordered == declared
    service.set_config_value('SCRIPT_DEFAULT_TIMEOUT', '45')
    assert runtime_config.SCRIPT_DEFAULT_TIMEOUT == 45
    assert service.build_config_payload()['items']
    service.reset_config_key('SCRIPT_DEFAULT_TIMEOUT')
    assert runtime_config.SCRIPT_DEFAULT_TIMEOUT == 300
    with pytest.raises(ValueError):
        service.set_config_value('SCRIPT_DEFAULT_TIMEOUT', '0')


class ScriptExecutionHarness(CommandExecutionMixin, CommandRuntimeMixin):
    pass


def test_script_runtime_uses_independent_timeout(script_settings, monkeypatch):
    service = script_settings
    service.set_config_value('SCRIPT_DEFAULT_TIMEOUT', '7')
    service.set_config_value('COMMAND_DEFAULT_STREAM_TIMEOUT', '99')
    owner = object.__new__(ScriptExecutionHarness)
    owner.execution_context = CommandExecutionContext(42)
    captures = []
    def fake_collect(code, kwargs=None, mode='', default_mode='', timeout=None):
        captures.append((code, timeout, owner.execution_context.timeout))
        return 1, 'completed'
    monkeypatch.setattr(owner, '_execute_python_collect', fake_collect)
    assert owner.execute_script_stream('print(123)') == (1, 'completed')
    assert captures == [('print(123)', 7, 7)]
    assert owner.execution_context.resolve_timeout() <= 7


def test_inproc_expired_budget_is_reported(script_settings, monkeypatch):
    script_settings.set_config_value('SCRIPT_DEFAULT_TIMEOUT', '1')
    owner = object.__new__(ScriptExecutionHarness)
    owner.execution_context = CommandExecutionContext(43)
    monkeypatch.setattr(owner, '_execute_python_collect', lambda *a, **kw: (1, 'printed'))
    monkeypatch.setattr(owner.execution_context, 'is_timeout_expired', lambda fallback_timeout=None: True)
    status, message = owner.execute_script_stream('print(123)')
    assert status == 0
    assert 'printed' in message and '1 seconds' in message


def test_subprocess_timeout_returns_terminal_error(script_settings, monkeypatch):
    import subprocess
    owner = object.__new__(ScriptExecutionHarness)
    owner.execution_context = CommandExecutionContext(44)
    monkeypatch.setattr(owner, '_execute_python_collect', lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('python', 300)))
    assert owner.execute_script_stream('import time') == (0, 'Script timed out after 300 seconds')
