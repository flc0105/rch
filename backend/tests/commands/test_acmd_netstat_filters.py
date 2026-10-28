"""ACMD netstat optional status and protocol filters, with legacy defaults preserved."""
import json
from types import SimpleNamespace

import pytest

from client.commands.arguments.registry import ArgumentCommandRegistry
from client.commands.common.providers.netstat_provider import PsutilNetstatProvider
from client.commands.platform.linux import LinuxCommands
from client.commands.platform.mac import MacCommands
from client.commands.platform.win import WindowsCommands
from server.application.command.command_planner import CommandPlanner


CONNECTIONS = [
    {'protocol': 'tcp', 'local_address': '0.0.0.0:443', 'remote_address': '*:*',
     'status': 'LISTEN', 'pid': 101, '_local_port': 443, '_remote_port': None},
    {'protocol': 'tcp', 'local_address': '127.0.0.1:8000', 'remote_address': '*:*',
     'status': 'LISTENING', 'pid': 102, '_local_port': 8000, '_remote_port': None},
    {'protocol': 'tcp', 'local_address': '127.0.0.1:1234', 'remote_address': '127.0.0.1:443',
     'status': 'ESTABLISHED', 'pid': 103, '_local_port': 1234, '_remote_port': 443},
    {'protocol': 'udp', 'local_address': '0.0.0.0:5353', 'remote_address': '*:*',
     'status': '-', 'pid': 104, '_local_port': 5353, '_remote_port': None},
]


def _execute(command, monkeypatch, platform='linux'):
    from client.commands.common.services.network import netstat_service
    monkeypatch.setattr(netstat_service, 'get_local_identity', lambda: SimpleNamespace(os_alias=platform))
    monkeypatch.setattr(PsutilNetstatProvider, 'collect', lambda self: list(CONNECTIONS))
    command_cls = {'linux': LinuxCommands, 'mac': MacCommands, 'win': WindowsCommands}[platform]
    registry = ArgumentCommandRegistry(command_cls(socket=SimpleNamespace()))
    return registry.execute(CommandPlanner.__new__(CommandPlanner).parse_argument_command(command))


def _json_rows(command, monkeypatch, platform='linux'):
    status, output = _execute(command + ' --json', monkeypatch, platform)
    assert status == 1, output
    return json.loads(output)


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
    status, output = _execute('acmd netstat -u -l', monkeypatch)
    assert status == 0
    assert 'No network connections match' in output


def test_help_includes_new_flags(monkeypatch):
    status, output = _execute('acmd help netstat', monkeypatch)
    assert status == 1
    for item in ('--status', '-l', '--protocol', '-t', '-u', '--json'):
        assert item in output
