"""Effect callbacks describe applied changes in final result, warnings stay interim."""
from types import SimpleNamespace
from client.config.manager import ConfigurationManager
from core.protocol.control import ConfigurationAction
from client.config.runtime_config_effects import warning


def test_config_change_appends_effect_note_without_duplicate_success_chunk():
    conn = SimpleNamespace(runtime=SimpleNamespace(features={'watchdog': True}))
    manager = ConfigurationManager(conn)
    manager.service = SimpleNamespace(set_config_value=lambda *args, **kwargs:
        SimpleNamespace(key='PROCESS_RECOVERY_WATCHDOG_ENABLED', old_value=False, new_value=True))
    manager.effects = lambda *args: ['Process Recovery Watchdog started.', warning('worker unavailable')]
    messages = []
    scope = SimpleNamespace(_checkpoint=lambda: None,
                            emit_progress=lambda message, level=None: messages.append((level, message)))
    status, result = manager.execute(scope, ConfigurationAction.SET, {'key': 'PROCESS_RECOVERY_WATCHDOG_ENABLED', 'value': True})
    assert status == 1
    assert 'PROCESS_RECOVERY_WATCHDOG_ENABLED updated:' in result['message']
    assert 'Process Recovery Watchdog started.' in result['message']
    assert messages == [('warning', 'worker unavailable')]
