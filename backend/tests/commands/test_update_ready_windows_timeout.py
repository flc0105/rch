"""Update startup can exceed 10 seconds while Windows loads and connects over TLS."""

import json
from types import SimpleNamespace

from client.commands.common.mixins import update_ops
from client.commands.common.mixins.update_ops import CommandUpdateMixin


def test_update_allows_ready_marker_after_12_seconds_without_server_changes(monkeypatch, tmp_path):
    now = [0.0]
    ready_path = tmp_path / 'ready.json'
    process = SimpleNamespace(pid=444, poll=lambda: None)

    def sleep(duration):
        now[0] += duration
        if now[0] >= 12 and not ready_path.exists():
            ready_path.write_text(json.dumps({'pid': 444, 'client_id': 'updated'}))

    monkeypatch.setattr(update_ops.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(update_ops.time, 'sleep', sleep)
    updater = CommandUpdateMixin()
    updater._checkpoint = lambda: None
    updater.UPDATE_READY_STABILIZE_SECONDS = 0.5
    updater.UPDATE_READY_POLL_INTERVAL_SECONDS = 0.25

    assert CommandUpdateMixin.UPDATE_READY_TIMEOUT_SECONDS == 30
    result = updater._wait_for_updated_client_ready(process, str(ready_path), '')
    assert result['client_id'] == 'updated'
    assert now[0] >= 12.5


def test_update_ready_wait_uses_monotonic_clock(monkeypatch, tmp_path):
    now = [0.0]
    ready_path = tmp_path / 'late-ready.json'
    child = SimpleNamespace(pid=45, poll=lambda: None)

    def sleep(duration):
        now[0] += duration
        if now[0] >= 11.0 and not ready_path.exists():
            ready_path.write_text(json.dumps({'pid': child.pid, 'client_id': 'after-clock-adjustment'}))

    monkeypatch.setattr(update_ops.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(update_ops.time, 'time', lambda: -1000000.0 if now[0] >= 1 else 1000000.0)
    monkeypatch.setattr(update_ops.time, 'sleep', sleep)
    updater = CommandUpdateMixin()
    updater._checkpoint = lambda: None
    updater.UPDATE_READY_STABILIZE_SECONDS = 0.25
    updater.UPDATE_READY_POLL_INTERVAL_SECONDS = 0.25
    assert updater._wait_for_updated_client_ready(child, str(ready_path), '')['client_id'] == 'after-clock-adjustment'
