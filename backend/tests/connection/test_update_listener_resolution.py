"""Update transport metadata is independent of advertised connection ports."""
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


def test_update_transport_and_tls_fingerprint(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, 'certificate_fingerprint',
                        lambda listener_id: 'a' * 64 if listener_id == 'tls-x' else '')
    assert manager.update_build_settings('tcp', '', 'python')['listener_id'] == 'tcp-default'
    settings = manager.update_build_settings('tls_tcp', 'a' * 64, 'python')
    assert settings['listener_id'] == 'tls-x'
    assert settings['tls_fingerprint'] == 'a' * 64
    with pytest.raises(ValueError):
        manager.update_build_settings('tls_tcp', 'b' * 64, 'python')
    with pytest.raises(ValueError):
        manager.update_build_settings('tls_tcp', '', 'python')
    with pytest.raises(ValueError):
        manager.update_build_settings('unknown', '', 'python')


def test_update_unpinned_listener_identity_is_optional(tmp_path):
    manager = _manager(tmp_path)
    manager._configs.append({'id': 'tcp-other', 'name': 'Other', 'protocol': 'tcp',
                             'port': 19999, 'enabled': True})
    assert manager.update_build_settings('tcp', '', 'python')['listener_id'] == ''
    assert manager.update_build_settings('tcp', '', 'python', 'tcp-other')['listener_id'] == 'tcp-other'
    manager._configs[2]['enabled'] = False
    assert manager.update_build_settings('tcp', '', 'python')['listener_id'] == 'tcp-default'
    manager._configs[0]['enabled'] = False
    assert manager.update_build_settings('tcp', '', 'python')['listener_id'] == ''
    with pytest.raises(ValueError):
        manager.update_build_settings('tcp', '', 'python', 'tcp-other')


def test_update_duplicate_verified_tls_pin_does_not_require_unique_listener(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    manager._configs.append({'id': 'tls-other', 'name': 'Other TLS', 'protocol': 'tls_tcp',
                             'port': 19443, 'enabled': True})
    monkeypatch.setattr(manager, 'certificate_fingerprint', lambda listener_id: 'a' * 64)
    settings = manager.update_build_settings('tls_tcp', 'a' * 64, 'python')
    assert settings['listener_id'] == ''
    assert settings['tls_fingerprint'] == 'a' * 64
    assert manager.update_build_settings('tls_tcp', 'a' * 64, 'python', 'tls-other')['listener_id'] == 'tls-other'


def test_manual_build_still_requires_selected_listener_port(tmp_path):
    manager = _manager(tmp_path)
    assert manager.build_settings('tcp-default', 9999, 'python')['listener_protocol'] == 'tcp'
    with pytest.raises(ValueError, match='Server port does not match selected listener'):
        manager.build_settings('tcp-default', 19999, 'python')
