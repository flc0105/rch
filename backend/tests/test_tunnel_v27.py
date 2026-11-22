"""TCP forwarding invariants retained by the shared-listener implementation."""
import socket

from test_tunnel_shared_tcp_v30 import CLIENT_ID, environment, target, mapping, unused_port
from tunnel.instances import validate_config


def test_saved_mappings_are_inactive_until_started(environment, target):
    env = environment
    port = unused_port()
    env.service.create(CLIENT_ID, 'idle', mapping('client', port, target))
    assert env.listener._tunnel_handler is None
    assert env.service.status(CLIENT_ID, 'idle')['status'] == 'stopped'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))


def test_start_stop_releases_port_and_stops_all(environment, target):
    env = environment
    a, b = unused_port(), unused_port()
    env.service.create(CLIENT_ID, 'first', mapping('client', a, target))
    env.service.create(CLIENT_ID, 'second', mapping('client', b, target))
    env.service.start(CLIENT_ID, 'first', env.remote)
    env.service.start(CLIENT_ID, 'second', env.remote)
    assert env.service.stop_all(CLIENT_ID, env.remote)['stopped'] == ['first', 'second']
    assert env.listener._tunnel_handler is None
    assert not env.service.list(CLIENT_ID)['connected']


def test_invalid_names_and_bad_tcp_ports(environment):
    env = environment
    for port in (0, 65536, -1, True, '18085'):
        try:
            validate_config({'listen_port': port, 'target_port': 8085})
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid port was accepted: {port!r}')
    try:
        env.service.create(CLIENT_ID, '../bad', {'listen_port': 18085, 'target_port': 8085})
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid name accepted')
