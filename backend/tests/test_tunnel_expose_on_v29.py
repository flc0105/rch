"""Expose-on choice never selects the outbound data TCP direction."""
import socket
from urllib.request import urlopen

import pytest

from test_tunnel_shared_tcp_v30 import CLIENT_ID, environment, target, mapping, unused_port
from tunnel.client import PassiveTunnel
from tunnel.ingress import SharedPortHandler
from tunnel.server import ActiveTunnel
from server.runtime.server_listener import ServerListener


@pytest.mark.parametrize('exposure', ['server', 'client'])
def test_exposure_has_no_effect_on_channel_dial_direction(environment, target, exposure):
    env = environment
    if env.mode == 'reverse':
        assert not hasattr(env.session, 'bind_dial_endpoint')
    else:
        assert env.session.bind_dial_endpoint[1] == env.port
    front = unused_port()
    env.service.create(CLIENT_ID, 'web', mapping(exposure, front, target))
    assert env.service.start(CLIENT_ID, 'web', env.remote)['status'] == 'running'
    assert urlopen(f'http://127.0.0.1:{front}/{env.mode}/{exposure}').read() == (
        f'RCH:/{env.mode}/{exposure}').encode()
    assert env.service.stop(CLIENT_ID, 'web', env.remote)['status'] == 'stopped'


def test_many_clients_share_one_server_listener_with_isolated_tokens(target):
    port = unused_port()
    listener = ServerListener(object(), {'id': 'tcp-default', 'host': '127.0.0.1', 'port': port})
    listener.start()
    handler = SharedPortHandler()
    connections = []
    try:
        for index in (1, 2):
            client_id = f'client-{index}'
            secret = ('a' if index == 1 else 'b') * 64
            passive = PassiveTunnel(secret)
            handler.register(client_id, passive)
            listener.set_tunnel_handler(handler)
            active = ActiveTunnel(secret, lambda: socket.create_connection(('127.0.0.1', port)), client_id)
            front = unused_port()
            passive.add(client_id, exposed=True, listen_host='127.0.0.1', listen_port=front,
                        target_host='127.0.0.1', target_port=1)
            active.add(client_id, exposed=False, listen_host='127.0.0.1', listen_port=1,
                       target_host='127.0.0.1', target_port=target)
            active.attach()
            connections.append((client_id, passive, active, front))
        for cid, passive, active, front in connections:
            assert active.connected and passive.connected
            assert urlopen(f'http://127.0.0.1:{front}/{cid}').read() == f'RCH:/{cid}'.encode()
        cid, passive, active, front = connections[0]
        handler.unregister(cid, passive)
        active.close()
        passive.close()
        assert not handler.empty
        assert urlopen(f'http://127.0.0.1:{connections[1][3]}/still').read() == b'RCH:/still'
        cid, passive, active, front = connections[1]
        handler.unregister(cid, passive)
        assert handler.empty
        listener.set_tunnel_handler(None)
    finally:
        for _cid, passive, active, _front in connections:
            active.close()
            passive.close()
        listener.set_tunnel_handler(None)
        listener.stop()
