"""Watchdog configuration must not occupy the foreground task indefinitely."""

import threading
from types import SimpleNamespace

from client.commands.common.mixins.runtime_config_ops import (
    _WatchdogUpdateQueue,
    CommandRuntimeConfigMixin,
)
from client.config import runtime_config


def test_slow_watchdog_update_returns_pending_then_processes_serially():
    coordinator = _WatchdogUpdateQueue()
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    order = []

    def slow():
        order.append('start')
        entered.set()
        assert release.wait(2)
        order.append('finish')
        return ['done']

    try:
        result = coordinator.submit(slow, 'PROCESS_WATCHDOG_ENABLED', wait_seconds=0.04)
        assert entered.is_set()
        assert any('still applying' in item for item in result)
        assert coordinator.submit(lambda: (order.append('second'), completed.set(), ['done'])[2],
                                  'LOCAL_WATCHDOG_ENABLED', wait_seconds=0.04)
        assert not completed.is_set()
    finally:
        release.set()
    assert completed.wait(2)
    assert order == ['start', 'finish', 'second']


def test_watchdog_config_applies_without_holding_foreground_checkpoint(monkeypatch):
    class Manager:
        def __init__(self):
            self.started = threading.Event()
        def start(self):
            self.started.set()
        def stop(self):
            pass

    manager = Manager()
    socket = SimpleNamespace(
        runtime=SimpleNamespace(features={'watchdog': True}),
        process_watchdog_manager=manager,
        guard_manager=None,
    )
    owner = CommandRuntimeConfigMixin()
    owner.socket = socket
    owner._checkpoint = lambda: None
    monkeypatch.setattr('client.commands.common.mixins.runtime_config_ops.is_launchd_managed_client', lambda: False)
    monkeypatch.setattr(runtime_config, 'REMOTE_HTTP_WATCHDOG_ENABLED', False)
    monkeypatch.setattr(runtime_config, 'LOCAL_WATCHDOG_ENABLED', False)
    outcome = owner._apply_runtime_config_side_effects('PROCESS_WATCHDOG_ENABLED', True)
    assert manager.started.is_set()
    assert 'Applied' in ''.join(outcome)
    assert getattr(socket, '_watchdog_update_queue', None) is not None
