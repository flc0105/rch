"""One-shot LAN Bind discovery on an explicitly chosen Server interface."""
import ipaddress
import secrets
import socket
import time

import psutil

from core.protocol.bind_discovery import DISCOVERY_PORT, make_packet, read_packet


def list_interfaces():
    interfaces = []
    stats = psutil.net_if_stats()
    for name, entries in psutil.net_if_addrs().items():
        if not getattr(stats.get(name), 'isup', False):
            continue
        for entry in entries:
            if entry.family != socket.AF_INET or not entry.netmask:
                continue
            try:
                address = ipaddress.IPv4Address(entry.address)
                network = ipaddress.IPv4Network(f'{entry.address}/{entry.netmask}', strict=False)
            except ValueError:
                continue
            if address.is_loopback or address.is_link_local or address.is_unspecified:
                continue
            broadcast = str(network.broadcast_address)
            if not entry.broadcast and network.prefixlen >= 31:
                continue
            interfaces.append({'name': name, 'address': str(address),
                               'broadcast': entry.broadcast or broadcast})
    return interfaces


def scan(interface_address, *, timeout=2.0):
    interface = next((item for item in list_interfaces() if item['address'] == interface_address), None)
    if interface is None:
        raise ValueError('Select a valid Server network interface')
    nonce = secrets.token_hex(8)
    devices = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((interface['address'], 0))
        sock.sendto(make_packet(action='discover', nonce=nonce),
                    (interface['broadcast'], DISCOVERY_PORT))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                raw, peer = sock.recvfrom(1025)
            except socket.timeout:
                break
            reply = read_packet(raw)
            if not reply or reply.get('nonce') != nonce:
                continue
            port = reply.get('port')
            transport = reply.get('transport')
            if type(port) is not int or not 1 <= port <= 65535 or transport not in ('tcp', 'mtls_tcp'):
                continue
            host = peer[0]  # Trust the datagram source, never an advertised IP field.
            key = (host, port, transport)
            devices[key] = {
                'host': host, 'port': port, 'transport': transport,
                'hostname': str(reply.get('hostname') or '')[:128],
                'os': str(reply.get('os') or '')[:64],
                'available': reply.get('available') is True,
            }
    return sorted(devices.values(), key=lambda item: (not item['available'], item['hostname'], item['host']))
