"""Tunnel is unavailable to Clients without removing the established protocol domain."""
from types import SimpleNamespace
from unittest.mock import Mock

from client.config.feature_config import resolve_features
from client.controls.registration import build_control_dispatcher
from core.protocol.control import ControlDomain, TunnelAction


def test_tunnel_disabled_in_python_client_capabilities():
    for platform in ('mac', 'win', 'linux', 'ios'):
        assert resolve_features(platform)['tunnel'] is False


def test_tunnel_control_rejected_without_importing_plugin():
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
    )
    # Dispatcher wiring needs the external-tool adapter, not external-tool execution.
    dispatcher = build_control_dispatcher(runtime)
    try:
        handler = dispatcher._actions[(ControlDomain.TUNNEL, TunnelAction.START)].handler
        assert handler(None, TunnelAction.START, {}) == (0, 'Tunnel disabled on Client')
    finally:
        dispatcher.disconnect()
