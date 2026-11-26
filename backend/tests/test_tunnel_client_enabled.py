"""Python Client Tunnel capability and lazy Control routing."""
from types import SimpleNamespace
from unittest.mock import Mock

from client.config.feature_config import resolve_features
from client.controls.registration import build_control_dispatcher
from core.protocol.control import ControlDomain, TunnelAction


def test_tunnel_available_on_all_python_platforms_and_can_be_disabled():
    for platform in ('mac', 'win', 'linux', 'ios'):
        assert resolve_features(platform, overrides={})['tunnel'] is True
        assert resolve_features(platform, overrides={'tunnel': False})['tunnel'] is False


def test_tunnel_requests_reach_lazy_adapter(monkeypatch):
    from tunnel import client as tunnel_client
    calls = []

    def execute(scope, action, payload):
        calls.append((scope, action, payload))
        return 1, {'connected': True}

    monkeypatch.setattr(tunnel_client, 'execute', execute)
    runtime = SimpleNamespace(
        execution=SimpleNamespace(context_store=Mock()),
        job_manager=SimpleNamespace(execute=Mock()),
        remote_files_manager=SimpleNamespace(execute=Mock(), prepare_paths=Mock(), actions=[]),
        script_manager=SimpleNamespace(execute=Mock(), cancel_policy=None),
        configuration_manager=SimpleNamespace(execute=Mock()),
        process_manager=SimpleNamespace(execute=Mock()),
        watchdog_control=SimpleNamespace(execute=Mock()),
        session_control=SimpleNamespace(execute=Mock()),
        clipboard_manager=None,
        features={"tunnel": True},
    )
    dispatcher = build_control_dispatcher(runtime)
    try:
        handler = dispatcher._actions[(ControlDomain.TUNNEL, TunnelAction.START)].handler
        scope = object()
        payload = {'name': 'demo'}
        assert handler(scope, TunnelAction.START, payload) == (1, {'connected': True})
        assert calls == [(scope, TunnelAction.START, payload)]
        runtime.features['tunnel'] = False
        assert handler(scope, TunnelAction.START, payload) == (0, 'Tunnel disabled on Client')
        assert len(calls) == 1
    finally:
        dispatcher.disconnect()
