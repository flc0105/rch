"""Exercise the installable standalone tunnel against real loopback TCP sockets."""
import concurrent.futures
import json
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from server.application.external_tools.external_tool_catalog_service import ExternalToolCatalogService
from server.application.external_tools.external_tool_runtime_service import ExternalToolRuntimeService

ROOT = Path(__file__).resolve().parents[1] / 'server/resources/external_tools'
NAME = 'rch-port-tunnel-v1.0.0-common-all.zip'
TOKEN = 'v33-test-token-not-for-production-' + 'x' * 16


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def await_port(port, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f'tcp listener {port} did not start')


class Echo:
    def __init__(self):
        self.port = free_port()
        self.stop = threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', self.port))
        self.sock.listen(32)
        self.sock.settimeout(.15)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self.echo, args=(conn,), daemon=True).start()

    @staticmethod
    def echo(conn):
        with conn:
            while True:
                data = conn.recv(65536)
                if not data:
                    try:
                        conn.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    return
                conn.sendall(data)

    def close(self):
        self.stop.set()
        self.sock.close()


@pytest.fixture
def executable(tmp_path):
    package = ROOT / 'tools' / NAME
    with zipfile.ZipFile(package) as archive:
        assert archive.namelist() == ['port_tunnel.py']
        archive.extractall(tmp_path)
    return str(tmp_path / 'port_tunnel.py')


@pytest.fixture
def processes():
    items = []
    yield items
    for process in reversed(items):
        process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)


def start(executable, processes, *params):
    p = subprocess.Popen([sys.executable, '-u', executable, *map(str, params)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    processes.append(p)
    return p


def transfer(port, body):
    with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
        sock.settimeout(5)
        sock.sendall(body)
        sock.shutdown(socket.SHUT_WR)
        result = bytearray()
        while True:
            part = sock.recv(65536)
            if not part:
                break
            result.extend(part)
        return bytes(result)


@pytest.mark.parametrize('expose_on', ['hub', 'agent'])
def test_both_listen_directions_and_concurrent_half_closed_streams(executable, processes, expose_on):
    target = Echo()
    port, forward = free_port(), free_port()
    try:
        hub = start(executable, processes, 'hub', '--channel-port', port, '--expose-on', expose_on,
                    '--listen-port', forward, '--target-port', target.port, '--token', TOKEN)
        await_port(port)
        agent = start(executable, processes, 'agent', '--channel-port', port, '--token', TOKEN)
        await_port(forward)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            payloads = [bytes([i]) * (100000 + 300 * i) for i in range(10)]
            result = list(pool.map(lambda body: transfer(forward, body), payloads))
        assert result == payloads
        assert hub.poll() is None and agent.poll() is None
    finally:
        target.close()


def test_rejects_invalid_token_without_disturbing_following_valid_agent(executable, processes):
    target = Echo()
    port, forward = free_port(), free_port()
    try:
        start(executable, processes, 'hub', '--channel-port', port, '--expose-on', 'hub',
              '--listen-port', forward, '--target-port', target.port, '--token', TOKEN)
        await_port(port)
        from struct import pack, unpack
        with socket.create_connection(('127.0.0.1', port), timeout=2) as sock:
            data = json.dumps({'role': 'control', 'token': 'wrong'}).encode()
            sock.sendall(pack('!I', len(data)) + data)
            size = unpack('!I', sock.recv(4))[0]
            assert json.loads(sock.recv(size))['ok'] is False
        start(executable, processes, 'agent', '--channel-port', port, '--token', TOKEN)
        await_port(forward)
        assert transfer(forward, b'authenticated stream') == b'authenticated stream'
    finally:
        target.close()


def test_catalog_payload_and_common_archive_are_installable():
    catalog = ExternalToolCatalogService(str(ROOT / 'metas'), str(ROOT / 'tools'))
    package = catalog.get_package('rch-port-tunnel')
    assert catalog.select_package_key(package, 'mac', 'arm64') == 'common-all'
    assert catalog.select_package_key(package, 'linux', 'amd64') == 'common-all'
    assert {module['tool_id'] for module in package['modules']} == {'rch-port-tunnel.hub', 'rch-port-tunnel.agent'}
    service = ExternalToolRuntimeService(catalog, command_execution_api=None)
    for role in ('hub', 'agent'):
        module = catalog.get_tool(f'rch-port-tunnel.{role}')
        payload = service.payload_builder.build_client_start_payload(
            module, params={'token': TOKEN}, platform_alias='mac', arch='arm64')
        argv = payload['runtime']['argv']
        assert argv[1] == role
        assert '--token' in argv and TOKEN in argv
        assert payload['launcher']['type'] == 'client_python'
        assert 'bin_port_tunnel' not in ' '.join(argv)
        assert payload['install']['install_dir'].startswith('~')
    with zipfile.ZipFile(ROOT / 'tools' / NAME) as archive:
        assert archive.testzip() is None


def test_cli_rejects_weak_secret_and_invalid_port(executable):
    for args in (('hub', '--listen-port', '0', '--target-port', '8085', '--token', TOKEN),
                 ('agent', '--token', 'short')):
        p = subprocess.run([sys.executable, executable, *args], capture_output=True, timeout=4)
        assert p.returncode != 0


def test_agent_stop_and_restart_reopens_exposed_port(executable, processes):
    target = Echo()
    channel, forward = free_port(), free_port()
    try:
        hub = start(executable, processes, 'hub', '--channel-port', channel, '--expose-on', 'hub',
                    '--listen-port', forward, '--target-port', target.port, '--token', TOKEN)
        await_port(channel)
        agent = start(executable, processes, 'agent', '--channel-port', channel, '--token', TOKEN)
        await_port(forward)
        assert transfer(forward, b'first agent') == b'first agent'
        agent.terminate()
        agent.wait(timeout=4)
        # Hub is still alive, and a second agent can claim the same authenticated channel.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', forward), timeout=.15):
                    time.sleep(.05)
            except OSError:
                break
        else:
            raise AssertionError('exposed port was not released after agent stopped')
        second = start(executable, processes, 'agent', '--channel-port', channel, '--token', TOKEN)
        await_port(forward)
        assert transfer(forward, b'second agent') == b'second agent'
        assert hub.poll() is None and second.poll() is None
    finally:
        target.close()
