"""Bind discovery for independent Client processes on the same host."""
import errno
import os
import secrets
import socket
import threading
import time

from core.device.local_identity import get_local_identity
from core.protocol.bind_discovery import DISCOVERY_PORT, make_packet, read_packet
from core.utils.logger import logger

_ANNOUNCE_INTERVAL = 0.75
_ENTRY_TTL = 3.0
_ELECTION_INTERVAL = 1.0


class BindDiscoveryResponder:
    def __init__(self, listener):
        self.listener = listener
        self._stop = threading.Event()
        self._socket = None
        self._thread = None
        self._leader = False
        self._instance_id = secrets.token_hex(8)
        self._entries = {}

    @staticmethod
    def _leader_socket():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('0.0.0.0', DISCOVERY_PORT))
            sock.settimeout(0.25)
            return sock
        except OSError:
            sock.close()
            raise

    @staticmethod
    def _is_port_busy(exc):
        return (exc.errno == errno.EADDRINUSE
                or (os.name == 'nt' and (exc.errno == errno.EACCES
                                          or getattr(exc, 'winerror', None) in (10013, 10048))))

    def start(self):
        if self._socket is not None:
            return
        self._leader = False
        self._entries.clear()
        try:
            sock = self._leader_socket()
            self._leader = True
        except OSError as exc:
            if not self._is_port_busy(exc):
                raise
            # A second process uses an ephemeral local socket for registration.
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind(('127.0.0.1', 0))
                sock.settimeout(0.25)
            except OSError:
                sock.close()
                raise
        self._stop.clear()
        self._socket = sock
        self._thread = threading.Thread(target=self._run, daemon=True, name='RCHBindDiscovery')
        self._thread.start()

    def _own_record(self, identity):
        return {
            'hostname': identity.hostname[:128], 'os': identity.os_type[:64],
            'port': self.listener.address[1], 'transport': self.listener.transport,
            'available': self.listener.available_for_discovery(),
        }

    def _announce(self, sock, action='register'):
        try:
            identity = get_local_identity()
            record = self._own_record(identity)
            sock.sendto(make_packet(action=action, nonce=self._instance_id, **record),
                        ('127.0.0.1', DISCOVERY_PORT))
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning('Bind discovery registration failed: %s', exc)

    def _receive(self, sock, now):
        try:
            raw, peer = sock.recvfrom(1025)
        except socket.timeout:
            return
        except OSError:
            return
        packet = read_packet(raw)
        if packet is None:
            return
        action = packet.get('action')
        if action in ('register', 'unregister'):
            # Local processes register on loopback; LAN announcements are ignored.
            if peer[0] != '127.0.0.1':
                return
            key = packet['nonce']
            if action == 'unregister':
                self._entries.pop(key, None)
                return
            port, transport = packet.get('port'), packet.get('transport')
            if type(port) is not int or not 1 <= port <= 65535 or transport not in ('tcp', 'mtls_tcp'):
                return
            self._entries[key] = (now, {
                'hostname': str(packet.get('hostname') or '')[:128],
                'os': str(packet.get('os') or '')[:64],
                'port': port, 'transport': transport,
                'available': packet.get('available') is True,
            })
            return
        if action != 'discover':
            return
        # One UDP response per Bind instance keeps the Server scanner unchanged.
        try:
            identity = get_local_identity()
            records = [self._own_record(identity)]
        except Exception as exc:
            logger.warning('Bind discovery identity unavailable: %s', exc)
            return
        for key, (updated, record) in list(self._entries.items()):
            if now - updated > _ENTRY_TTL:
                self._entries.pop(key, None)
            else:
                records.append(record)
        for record in records:
            try:
                sock.sendto(make_packet(nonce=packet['nonce'], **record), peer)
            except OSError:
                break

    def _try_takeover(self, sock):
        try:
            leader_sock = self._leader_socket()
        except OSError as exc:
            if not self._is_port_busy(exc):
                logger.warning('Bind discovery election failed: %s', exc)
            return sock
        # No long-lived coordinator: another Bind takes over after its exit.
        self._leader = True
        self._entries.clear()
        self._socket = leader_sock
        sock.close()
        return leader_sock

    def _run(self):
        sock = self._socket
        next_announce = 0.0
        next_election = time.monotonic() + _ELECTION_INTERVAL
        while not self._stop.is_set():
            now = time.monotonic()
            if not self._leader:
                if now >= next_election:
                    sock = self._try_takeover(sock)
                    next_election = now + _ELECTION_INTERVAL
                if not self._leader and now >= next_announce:
                    self._announce(sock)
                    next_announce = now + _ANNOUNCE_INTERVAL
            if self._leader:
                self._receive(sock, now)
            else:
                # The local registration socket never accepts LAN discoveries.
                self._stop.wait(0.25)

    def close(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        sock, self._socket = self._socket, None
        if sock is not None:
            if not self._leader:
                self._announce(sock, action='unregister')
            sock.close()
