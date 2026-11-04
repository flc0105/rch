"""Select the existing TCP/TLS listener for a rebuild, without touching socket frames."""
from types import SimpleNamespace

import pytest

from server.runtime.listener_manager import ListenerManager


def _manager(tmp_path):
    manager = ListenerManager(SimpleNamespace(address=('127.0.0.1', 9999)), str(tmp_path / 'listeners.json'))
    manager._configs = [
        {'id': 'tcp-default', 'name': 'TCP', 'protocol': 'tcp', 'port': 9999, 'enabled': True},
        {'id': 'tls-x', 'name': 'Secure', 'protocol': 'tls_tcp', 'port': 9443, 'enabled': True},
    ]
    return manager


def test_update_resolves_legacy_port_only_and_tls_fingerprint(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, 'certificate_fingerprint',
                        lambda listener_id: 'a' * 64 if listener_id == 'tls-x' else '')
    assert manager.resolve_update_listener(9999) == 'tcp-default'
    assert manager.resolve_update_listener(9443) == 'tls-x'
    assert manager.resolve_update_listener(9443, 'tls_tcp', 'a' * 64) == 'tls-x'
    with pytest.raises(ValueError):
        manager.resolve_update_listener(9443, 'tcp')
    with pytest.raises(ValueError):
        manager.resolve_update_listener(9443, 'tls_tcp', 'b' * 64)


def test_update_refuses_ambiguous_or_disabled_listener(tmp_path):
    manager = _manager(tmp_path)
    manager._configs[1]['port'] = 9999
    with pytest.raises(ValueError):
        manager.resolve_update_listener(9999)
    manager._configs[1]['enabled'] = False
    assert manager.resolve_update_listener(9999) == 'tcp-default'
    with pytest.raises(ValueError):
        manager.resolve_update_listener(9443)
