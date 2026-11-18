"""Script timeout is independent from shell streaming timeout."""

import pytest
from core.protocol.script_execution import ScriptRunModes, ExecutionMode, OutputMode

MODES = ScriptRunModes(ExecutionMode.INPROC, OutputMode.COLLECT)

from client.config import runtime_config
from client.scripts.manager import ScriptExecution
from client.runtime.execution.python_execution.service import PythonExecutionService
from client.runtime.execution.scope import ExecutionRuntimeMixin
from client.config.runtime_config_service import RuntimeConfigService
from client.runtime.execution.context import ExecutionContext


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


class ScriptExecutionHarness(ScriptExecution):
    pass


def test_script_runtime_uses_independent_timeout(script_settings, monkeypatch):
    service = script_settings
    service.set_config_value('SCRIPT_DEFAULT_TIMEOUT', '7')
    service.set_config_value('COMMAND_DEFAULT_STREAM_TIMEOUT', '99')
    owner = object.__new__(ScriptExecutionHarness)
    owner.execution_context = ExecutionContext(42)
    captures = []
    def fake_execute(self, code, kwargs=None, mode='', default_mode='', timeout=None, script_name=None, stream=False):
        captures.append((code, timeout, owner.execution_context.timeout, stream))
        return 1, 'completed'
    monkeypatch.setattr(PythonExecutionService, 'execute', fake_execute)
    assert owner.run_script('print(123)', modes=MODES) == (1, 'completed')
    assert captures == [('print(123)', 7, 7, False)]
    assert owner.execution_context.resolve_timeout() <= 7


def test_inproc_expired_budget_is_reported(script_settings, monkeypatch):
    script_settings.set_config_value('SCRIPT_DEFAULT_TIMEOUT', '1')
    owner = object.__new__(ScriptExecutionHarness)
    owner.execution_context = ExecutionContext(43)
    monkeypatch.setattr(PythonExecutionService, 'execute', lambda *a, **kw: (1, 'printed'))
    monkeypatch.setattr(owner.execution_context, 'is_timeout_expired', lambda fallback_timeout=None: True)
    status, message = owner.run_script('print(123)', modes=MODES)
    assert status == 0
    assert 'printed' in message['text'] and '1 seconds' in message['text'] and message['failure_reason'] == 'timed_out'


def test_subprocess_timeout_returns_terminal_error(script_settings, monkeypatch):
    import subprocess
    owner = object.__new__(ScriptExecutionHarness)
    owner.execution_context = ExecutionContext(44)
    monkeypatch.setattr(PythonExecutionService, 'execute', lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('python', 300)))
    status, result = owner.run_script('import time', modes=ScriptRunModes(ExecutionMode.SUBPROCESS_PIPE, OutputMode.COLLECT))
    assert status == 0 and result['failure_reason'] == 'timed_out'
    assert result['text'] == 'Script timed out after 300 seconds'
