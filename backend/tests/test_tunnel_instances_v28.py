"""Saved Tunnel CRUD and CLI boundaries under the channel-port-free schema."""
import pytest

from test_tunnel_shared_tcp_v30 import CLIENT_ID, environment, target, mapping, unused_port


def test_create_edit_remove_require_stopped_state(environment, target):
    env = environment
    front = unused_port()
    env.service.create(CLIENT_ID, 'docs', mapping('client', front, target))
    assert env.service.edit(CLIENT_ID, 'docs', {'target_port': target})['target_port'] == target
    env.service.start(CLIENT_ID, 'docs', env.remote)
    with pytest.raises(ValueError, match='Stop the tunnel'):
        env.service.edit(CLIENT_ID, 'docs', {'target_port': target})
    with pytest.raises(ValueError, match='Stop the tunnel'):
        env.service.remove(CLIENT_ID, 'docs')
    env.service.stop(CLIENT_ID, 'docs', env.remote)
    assert env.service.remove(CLIENT_ID, 'docs') == {'name': 'docs', 'deleted': True}


def test_same_exposed_side_duplicate_port_rejected(environment, target):
    env = environment
    front = unused_port()
    env.service.create(CLIENT_ID, 'first', mapping('server', front, target))
    with pytest.raises(ValueError, match='already assigned'):
        env.service.create(CLIENT_ID, 'second', mapping('server', front, target))
    env.service.create(CLIENT_ID, 'other', mapping('client', front, target))


def test_cli_registered_options_omit_dedicated_channel_port():
    from server.application.command.server_builtin_registry import SERVER_COMMAND_SPECS, SERVER_COMMAND_REGISTRY
    commands = {spec.name: spec for spec in SERVER_COMMAND_SPECS}
    tunnel = commands['tunnel']
    for name in ('create', 'edit', 'start'):
        action = tunnel.child(name)
        assert '--channel-port' not in action.usage
        assert 'channel_port' not in str(action.argument_spec)
    from core.commands.argument_errors import ArgumentCommandValidationError
    with pytest.raises(ArgumentCommandValidationError, match='Unknown option: --channel-port'):
        SERVER_COMMAND_REGISTRY.parse_invocation(
            'tunnel', 'create --name x --listen-port 18085 --target-port 8085 --channel-port 9444')
