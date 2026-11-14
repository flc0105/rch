"""Feature-controlled runtime configuration visibility."""
import pytest
from client.config.runtime_config_service import RuntimeConfigService
from client.config.feature_config import resolve_features


@pytest.mark.parametrize("platform,expected", [("ios", False), ("linux", False), ("mac", True), ("win", True)])
def test_screen_strategy_follows_effective_feature(platform, expected):
    features = resolve_features(platform)
    service = RuntimeConfigService(features=features)
    assert ('SCREEN_FRAME_STRATEGY' in {i[0] for i in service.list_config_items()}) is expected
    assert ('SCREEN_FRAME_STRATEGY' in {i['key'] for i in service.build_config_payload()['items']}) is expected
    assert ('SCREEN_FRAME_STRATEGY' in {i[0] for i in service.list_config_items(include_hidden=True)}) is expected
    assert service.is_supported_key('SCREEN_FRAME_STRATEGY') is expected


def test_explicit_feature_override_restores_screen_strategy_on_linux():
    service = RuntimeConfigService(features=resolve_features('linux', {'screen_view': True}))
    assert service.is_supported_key('SCREEN_FRAME_STRATEGY')


def test_removed_idle_timeout_options_are_not_registered():
    service = RuntimeConfigService()
    for key in ('HTTP_TRANSFER_IDLE_TIMEOUT_ENABLED', 'HTTP_TRANSFER_IDLE_TIMEOUT_SECONDS'):
        assert not service.is_known_config_key(key)
        assert not service.is_supported_key(key)
        assert key not in {item['key'] for item in service.build_config_payload()['items']}


def test_configuration_control_get_uses_runtime_features():
    from client.config.manager import ConfigurationManager
    from core.protocol.control import ConfigurationAction
    from types import SimpleNamespace
    manager = ConfigurationManager(None, features={'screen_view': False})
    scope = SimpleNamespace(_checkpoint=lambda: None, _send_interim_result=lambda *_: None)
    status, payload = manager.execute(scope, ConfigurationAction.GET, {})
    assert status == 1
    assert 'SCREEN_FRAME_STRATEGY' not in {item['key'] for item in payload['data']['items']}


def test_legacy_http_upload_uses_private_fixed_network_timeout(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from client.runtime.http_transfer.strategies.legacy import LegacyHttpTransferStrategy

    path = tmp_path / 'sample.txt'
    path.write_text('sample', encoding='utf8')
    session = SimpleNamespace(post=Mock(return_value=object()), close=Mock())
    strategy = LegacyHttpTransferStrategy(SimpleNamespace(_set_cancel_policy=Mock()))
    monkeypatch.setattr(strategy, 'create_http_session', lambda: session)
    strategy.upload_file(str(path), 'https://example.invalid/upload', {})
    assert session.post.call_args.kwargs['timeout'] == (15, 120)
    session.close.assert_called_once()
