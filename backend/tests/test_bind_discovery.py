"""Real UDP discovery and unchanged Bind TCP admission."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from client.connection.bind_listener import BindListener
from core.protocol.bind_discovery import make_packet, read_packet
from server.application.connection import bind_discovery as scanner
from client.connection import bind_discovery as responder


def _free_port(sock_type):
    with socket.socket(socket.AF_INET, sock_type) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _listener(monkeypatch, *, discovery_enabled=True, host='0.0.0.0', transport='tcp'):
    udp = _free_port(socket.SOCK_DGRAM)
    monkeypatch.setattr(scanner, 'DISCOVERY_PORT', udp)
    monkeypatch.setattr(responder, 'DISCOVERY_PORT', udp)
    monkeypatch.setattr(responder, 'get_local_identity', lambda: SimpleNamespace(
        hostname='test-bind', os_type='Linux',
    ))
    monkeypatch.setattr('client.update.signals.report_ready', lambda *args: None)
    tcp = _free_port(socket.SOCK_STREAM)
    if transport == 'mtls_tcp':
        monkeypatch.setattr('client.connection.bind_listener.create_context', lambda *args, **kw: object())
    listener = BindListener({'connection_mode': 'bind', 'server_transport': transport,
                             'bind_host': host, 'bind_port': tcp,
                             'bind_discovery_enabled': discovery_enabled})
    return listener, udp


def test_local_udp_discovery_does_not_claim_tcp_session(monkeypatch):
    listener, _ = _listener(monkeypatch)
    monkeypatch.setattr(scanner, 'list_interfaces', lambda: [
        {'name': 'lo-test', 'address': '127.0.0.1', 'broadcast': '127.0.0.1'},
    ])
    listener.start()
    try:
        devices = scanner.scan('127.0.0.1', timeout=.3)
        assert len(devices) == 1
        assert devices[0] == {'host': '127.0.0.1', 'port': listener.address[1],
                              'transport': 'tcp', 'hostname': 'test-bind',
                              'os': 'Linux', 'available': True}
        assert not listener._occupied
        # A real TCP connection is still admitted after UDP scanning.
        with socket.create_connection(('127.0.0.1', listener.address[1]), timeout=2) as sock:
            admitted = listener.accept()
            assert admitted.getpeername()[1] == sock.getsockname()[1]
            admitted.close()
        listener.release_session()
        with listener._lock:
            listener._occupied = True
        assert scanner.scan('127.0.0.1', timeout=.3)[0]['available'] is False
    finally:
        listener.close()
    assert scanner.scan('127.0.0.1', timeout=.3) == []


def test_discovery_can_be_disabled_without_affecting_bind(monkeypatch):
    listener, _ = _listener(monkeypatch, discovery_enabled=False)
    listener.start()
    try:
        assert listener._discovery is None
        with socket.create_connection(('127.0.0.1', listener.address[1]), timeout=2):
            accepted = listener.accept()
            accepted.close()
    finally:
        listener.close()


def test_loopback_bind_does_not_announce_on_lan(monkeypatch):
    listener, _ = _listener(monkeypatch, host='127.0.0.1')
    listener.start()
    try:
        assert listener._discovery is None
    finally:
        listener.close()


def test_invalid_udp_packets_and_interface_rejected(monkeypatch):
    assert read_packet(b'garbage') is None
    assert read_packet(b'{}') is None
    assert read_packet(b'x' * 1025) is None
    assert read_packet(make_packet(action='discover', nonce='not-a-nonce')) is None
    assert read_packet(make_packet(action='discover', nonce='a' * 16))['action'] == 'discover'
    monkeypatch.setattr(scanner, 'list_interfaces', lambda: [
        {'name': 'lan', 'address': '192.0.2.10', 'broadcast': '192.0.2.255'},
    ])
    with pytest.raises(ValueError, match='network interface'):
        scanner.scan('192.0.2.123')


def test_mtls_client_discovery_advertises_transport_without_tls_handshake(monkeypatch):
    listener, _ = _listener(monkeypatch, transport='mtls_tcp')
    monkeypatch.setattr(scanner, 'list_interfaces', lambda: [
        {'name': 'loopback-test', 'address': '127.0.0.1', 'broadcast': '127.0.0.1'},
    ])
    listener.start()
    try:
        devices = scanner.scan('127.0.0.1', timeout=.2)
        assert len(devices) == 1
        assert devices[0]['transport'] == 'mtls_tcp'
        assert devices[0]['available'] is True
        assert not listener._occupied
    finally:
        listener.close()


def test_discovery_udp_port_collision_does_not_stop_bind_tcp(monkeypatch):
    listener, udp_port = _listener(monkeypatch)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
        occupied.bind(('0.0.0.0', udp_port))
        listener.start()
        try:
            # Registration is best-effort when an unrelated service owns UDP.
            assert listener._discovery is not None
            with socket.create_connection(('127.0.0.1', listener.address[1]), timeout=2):
                session_socket = listener.accept()
                session_socket.close()
        finally:
            listener.close()


def test_same_host_multiple_bind_instances_are_discovered(monkeypatch):
    first, udp_port = _listener(monkeypatch)
    monkeypatch.setattr('client.connection.bind_listener.create_context', lambda *args, **kwargs: object())
    second = BindListener({'connection_mode': 'bind', 'server_transport': 'mtls_tcp',
                           'bind_host': '0.0.0.0', 'bind_port': _free_port(socket.SOCK_STREAM)})
    # Both listeners use the same discovery port, but different TCP ports.
    monkeypatch.setattr(scanner, 'list_interfaces', lambda: [
        {'name': 'test', 'address': '127.0.0.1', 'broadcast': '127.0.0.1'},
    ])
    first.start()
    second.start()
    try:
        deadline = time.monotonic() + 4
        while True:
            devices = scanner.scan('127.0.0.1', timeout=0.2)
            if len(devices) == 2 or time.monotonic() > deadline:
                break
        assert {(d['port'], d['transport']) for d in devices} == {
            (first.address[1], 'tcp'), (second.address[1], 'mtls_tcp'),
        }
        with second._lock:
            second._occupied = True
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            devices = scanner.scan('127.0.0.1', timeout=0.15)
            state = {d['port']: d['available'] for d in devices}
            if state.get(second.address[1]) is False:
                break
        assert state[first.address[1]] is True
        assert state[second.address[1]] is False
        with socket.create_connection(('127.0.0.1', first.address[1]), timeout=2):
            pass  # Existing TCP Bind admission remains independent of UDP.
    finally:
        second.close()
        first.close()


_CHILD_BIND = r"""
import sys, time
from pathlib import Path
from client.connection import bind_discovery
from client.connection import bind_listener
from client.update import signals
bind_discovery.DISCOVERY_PORT = int(sys.argv[1])
signals.report_ready = lambda *args: None
bind_listener.create_context = lambda *args, **kwargs: object()
listener = bind_listener.BindListener({
    'connection_mode': 'bind', 'server_transport': sys.argv[3],
    'bind_host': '0.0.0.0', 'bind_port': int(sys.argv[2]),
})
listener.start()
Path(sys.argv[4]).write_text('ready')
try:
    while True:
        time.sleep(0.25)
finally:
    listener.close()
"""


def test_independent_bind_processes_failover_and_expiry(monkeypatch, tmp_path):
    udp_port = _free_port(socket.SOCK_DGRAM)
    monkeypatch.setattr(scanner, 'DISCOVERY_PORT', udp_port)
    monkeypatch.setattr(scanner, 'list_interfaces', lambda: [
        {'name': 'lo-test', 'address': '127.0.0.1', 'broadcast': '127.0.0.1'},
    ])
    env = os.environ.copy()
    backend = str(Path(__file__).resolve().parents[1])
    env['PYTHONPATH'] = os.pathsep.join(filter(None, (backend, env.get('PYTHONPATH'))))
    processes = []
    ports = [_free_port(socket.SOCK_STREAM) for _ in range(3)]

    def launch(index, transport):
        ready_file = tmp_path / f'bind-{index}.ready'
        log_file = (tmp_path / f'bind-{index}.log').open('w')
        proc = subprocess.Popen(
            [sys.executable, '-u', '-c', _CHILD_BIND, str(udp_port),
             str(ports[index]), transport, str(ready_file)],
            env=env, stdout=log_file, stderr=subprocess.STDOUT,
        )
        log_file.close()
        processes.append(proc)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not ready_file.exists():
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        assert ready_file.exists(), (tmp_path / f'bind-{index}.log').read_text()
        return proc

    def wait_for_ports(expected, timeout=6):
        deadline = time.monotonic() + timeout
        found = []
        while time.monotonic() < deadline:
            found = scanner.scan('127.0.0.1', timeout=0.15)
            if {item['port'] for item in found} == expected:
                return found
            time.sleep(0.10)
        assert {item['port'] for item in found} == expected, found
        return found

    try:
        first = launch(0, 'tcp')
        second = launch(1, 'mtls_tcp')
        third = launch(2, 'tcp')
        found = wait_for_ports(set(ports))
        assert {d['port']: d['transport'] for d in found}[ports[1]] == 'mtls_tcp'
        # Abrupt follower exit: its registration ages out without clean unregister.
        third.kill()
        third.wait(timeout=4)
        wait_for_ports(set(ports[:2]), timeout=7)
        # Abrupt coordinator exit: a follower takes over on the same UDP port.
        first.kill()
        first.wait(timeout=4)
        found = wait_for_ports({ports[1]}, timeout=7)
        assert found[0]['transport'] == 'mtls_tcp'
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=4)
