"""Update should reuse its original local handoff and only preserve Listener build metadata."""
import json
from types import SimpleNamespace

import pytest
from client.commands.shell.common import maintenance as update_ops
from client.commands.shell.common.maintenance import ShellMaintenanceCommands


def test_update_payload_selects_original_tcp(monkeypatch):
    monkeypatch.setattr(update_ops, 'RUNTIME_CONFIG', {'server_transport': 'tcp', 'server_tls_fingerprint': ''})
    data = ShellMaintenanceCommands._build_update_request_payload(None)
    assert data['source'] == 'update'
    assert data['server_transport'] == 'tcp'
    assert data['server_tls_fingerprint'] == ''


def test_update_payload_preserves_pinned_tls(monkeypatch):
    fp = 'a' * 64
    monkeypatch.setattr(update_ops, 'RUNTIME_CONFIG', {'server_transport': 'tls_tcp', 'server_tls_fingerprint': fp})
    data = ShellMaintenanceCommands._build_update_request_payload(None)
    assert data['source'] == 'update'
    assert data['server_transport'] == 'tls_tcp'
    assert data['server_tls_fingerprint'] == fp


def test_update_ready_uses_local_marker_without_http_query(tmp_path):
    path = tmp_path / 'ready.json'
    path.write_text(json.dumps({'pid': 22113, 'client_id': 'new-client', 'client_revision': 'rev'}))
    updater = ShellMaintenanceCommands()
    updater._checkpoint = lambda: None
    updater.UPDATE_READY_TIMEOUT_SECONDS = .06
    updater.UPDATE_READY_STABILIZE_SECONDS = .01
    updater.UPDATE_READY_POLL_INTERVAL_SECONDS = .001
    child = SimpleNamespace(pid=22113, poll=lambda: None)
    assert updater._wait_for_updated_client_ready(child, str(path), '')['client_id'] == 'new-client'
    assert not hasattr(updater, '_is_updated_client_registered')


def test_update_ready_candidate_failure_does_not_look_connected(tmp_path):
    updater = ShellMaintenanceCommands()
    updater._checkpoint = lambda: None
    updater._read_update_startup_error = lambda path: ''
    updater.UPDATE_READY_TIMEOUT_SECONDS = .02
    updater.UPDATE_READY_POLL_INTERVAL_SECONDS = .001
    child = SimpleNamespace(pid=22114, poll=lambda: 1)
    with pytest.raises(RuntimeError, match='exited before handshake'):
        updater._wait_for_updated_client_ready(child, str(tmp_path / 'missing.json'), '')
