"""ACMD netstat filters, platform collectors and standalone registration."""
import json
import socket
import sys
from types import SimpleNamespace

import pytest

import client.commands.acmd.standalone.netstat as netstat_module
from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.acmd.common.network import ACMDNetworkCommands
from client.commands.runtime.hosts import LinuxCommands, MacCommands, WindowsCommands, iOSCommands
from server.application.command.command_planner import CommandPlanner


CONNECTIONS = [
    {'protocol': 'tcp', 'local_address': '0.0.0.0:443', 'remote_address': '*:*',
     'status': 'LISTEN', 'pid': 101, 'local_port': 443, 'remote_port': None},
    {'protocol': 'tcp', 'local_address': '127.0.0.1:8000', 'remote_address': '*:*',
     'status': 'LISTENING', 'pid': 102, 'local_port': 8000, 'remote_port': None},
    {'protocol': 'tcp', 'local_address': '127.0.0.1:1234', 'remote_address': '127.0.0.1:443',
     'status': 'ESTABLISHED', 'pid': 103, 'local_port': 1234, 'remote_port': 443},
    {'protocol': 'udp', 'local_address': '0.0.0.0:5353', 'remote_address': '*:*',
     'status': '-', 'pid': 104, 'local_port': 5353, 'remote_port': None},
]


def _execute(command, monkeypatch, platform='linux', connections=None):
    selected = CONNECTIONS if connections is None else connections
    monkeypatch.setattr(
        netstat_module,
        'collect_connections',
        lambda: [dict(row) for row in selected],
    )
    command_cls = {'linux': LinuxCommands, 'mac': MacCommands, 'win': WindowsCommands}[platform]
    registry = ArgumentCommandRegistry(command_cls(socket=SimpleNamespace()))
    return registry.execute(CommandPlanner.__new__(CommandPlanner).parse_argument_command(command))


def _json_rows(command, monkeypatch, platform='linux'):
    status, output = _execute(command + ' --json', monkeypatch, platform)
    assert status == 1, output
    return json.loads(output)


def test_standalone_is_mounted_directly_and_platform_scoped():
    assert ACMDNetworkCommands.netstat is netstat_module.netstat
    assert netstat_module.netstat.argument_command_platforms == ('mac', 'win', 'linux')
    assert netstat_module.NETSTAT_PLATFORMS == ('mac', 'win', 'linux')
    assert not {
        '_acmd_netstat', '_get_netstat_service', '_acmd_netstat_common'
    }.intersection(ACMDNetworkCommands.__dict__)

    ios_registry = ArgumentCommandRegistry(iOSCommands(socket=SimpleNamespace()))
    assert not ios_registry.has_command('netstat')
    assert 'acmd netstat' not in {
        item['name'] for item in ios_registry.get_manifest_payload()
    }


@pytest.mark.parametrize('platform', ['linux', 'mac', 'win'])
def test_default_unfiltered_and_original_columns(monkeypatch, platform):
    rows = _json_rows('acmd netstat', monkeypatch, platform)
    assert len(rows) == 4
    assert all(list(row) == ['protocol', 'local_address', 'remote_address', 'status', 'pid'] for row in rows)
    assert len(_json_rows('acmd netstat 443', monkeypatch, platform)) == 2
    assert len(_json_rows('acmd netstat --port 443', monkeypatch, platform)) == 2
    assert _execute('acmd netstat', monkeypatch, platform)[0] == 1


@pytest.mark.parametrize('command,expected_pids', [
    ('acmd netstat --status LISTENING', [101, 102]),
    ('acmd netstat --status listen', [101, 102]),
    ('acmd netstat -l', [101, 102]),
    ('acmd netstat --protocol tcp', [101, 102, 103]),
    ('acmd netstat -t', [101, 102, 103]),
    ('acmd netstat --protocol udp', [104]),
    ('acmd netstat -u', [104]),
    ('acmd netstat -l -t', [101, 102]),
    ('acmd netstat --status LISTENING --protocol tcp --port 443', [101]),
    ('acmd netstat -u --port 5353', [104]),
    ('acmd netstat --status ESTABLISHED', [103]),
])
def test_optional_filters(monkeypatch, command, expected_pids):
    rows = _json_rows(command, monkeypatch)
    assert sorted(item['pid'] for item in rows) == expected_pids


@pytest.mark.parametrize('command,error', [
    ('acmd netstat --protocol icmp', 'Invalid protocol'),
    ('acmd netstat -t -u', 'Choose either'),
    ('acmd netstat -t --protocol udp', 'Conflicting protocol'),
    ('acmd netstat -l --status ESTABLISHED', 'conflicts'),
    ('acmd netstat --port 65536', 'Port out of range'),
    ('acmd netstat --unknown', 'Unknown option'),
])
def test_invalid_filters(monkeypatch, command, error):
    status, output = _execute(command, monkeypatch)
    assert status == 0
    assert error in output


def test_no_matches_reports_filters(monkeypatch):
    status, output = _execute('acmd netstat -u -l', monkeypatch, connections=[CONNECTIONS[-1]])
    assert status == 0
    assert 'No network connections match' in output


def test_help_includes_new_flags(monkeypatch):
    status, output = _execute('acmd help netstat', monkeypatch)
    assert status == 1
    for item in ('--status', '-l', '--protocol', '-t', '-u', '--json'):
        assert item in output


def test_collector_uses_shared_per_process_psutil_api_and_skips_access_denied(monkeypatch):
    class AccessDenied(Exception):
        pass

    class NoSuchProcess(Exception):
        pass

    connection = SimpleNamespace(
        type=socket.SOCK_DGRAM,
        laddr=('::1', 5353, 0, 0),
        raddr=(),
        status=None,
    )

    class Process:
        def __init__(self, pid, error=None):
            self.pid = pid
            self.error = error

        def net_connections(self, kind):
            assert kind == 'inet'
            if self.error:
                raise self.error
            return [connection]

    fake_psutil = SimpleNamespace(
        AccessDenied=AccessDenied,
        NoSuchProcess=NoSuchProcess,
        process_iter=lambda _attrs: [
            Process(123), Process(456, AccessDenied()), Process(789, NoSuchProcess())
        ],
        net_connections=lambda **_kwargs: pytest.fail('collector must use per-process enumeration'),
    )
    monkeypatch.setitem(sys.modules, 'psutil', fake_psutil)

    rows = netstat_module.collect_connections()
    assert rows == [{
        'protocol': 'udp',
        'local_address': '[::1]:5353',
        'remote_address': '*:*',
        'status': '-',
        'pid': 123,
        'local_port': 5353,
        'remote_port': None,
    }]


def test_collector_reports_access_denied_when_no_process_is_readable(monkeypatch):
    class AccessDenied(Exception):
        pass

    class NoSuchProcess(Exception):
        pass

    class Process:
        pid = 123

        def net_connections(self, kind):
            raise AccessDenied()

    fake_psutil = SimpleNamespace(
        AccessDenied=AccessDenied,
        NoSuchProcess=NoSuchProcess,
        process_iter=lambda _attrs: [Process()],
    )
    monkeypatch.setitem(sys.modules, 'psutil', fake_psutil)

    with pytest.raises(RuntimeError, match='1 processes were denied'):
        netstat_module.collect_connections()



def test_collector_falls_back_to_legacy_psutil_process_connections(monkeypatch):
    connection = SimpleNamespace(
        type=socket.SOCK_STREAM,
        laddr=('127.0.0.1', 9000),
        raddr=(),
        status='LISTEN',
    )

    class LegacyProcess:
        pid = 789

        def connections(self, kind):
            assert kind == 'inet'
            return [connection]

    fake_psutil = SimpleNamespace(
        AccessDenied=type('AccessDenied', (Exception,), {}),
        NoSuchProcess=type('NoSuchProcess', (Exception,), {}),
        process_iter=lambda _attrs: [LegacyProcess()],
    )
    monkeypatch.setitem(sys.modules, 'psutil', fake_psutil)

    rows = netstat_module.collect_connections()
    assert len(rows) == 1
    assert rows[0]['pid'] == 789
    assert rows[0]['local_port'] == 9000


def test_collector_reports_empty_table(monkeypatch):
    fake_psutil = SimpleNamespace(
        AccessDenied=type('AccessDenied', (Exception,), {}),
        NoSuchProcess=type('NoSuchProcess', (Exception,), {}),
        process_iter=lambda _attrs: [],
    )
    monkeypatch.setitem(sys.modules, 'psutil', fake_psutil)

    with pytest.raises(RuntimeError, match='psutil returned no TCP/UDP network connections'):
        netstat_module.collect_connections()


def test_ipv6_address_formatting_preserves_port():
    assert netstat_module.format_address(('2001:db8::1', 443, 0, 0)) == ('[2001:db8::1]:443', 443)
