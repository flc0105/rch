"""ifconfig is a four-platform standalone ACMD with the former default view."""

import ctypes
import json
import socket
from types import SimpleNamespace

import pytest

from client.commands.acmd.registry import ArgumentCommandRegistry
from client.commands.acmd.common.network import ACMDNetworkCommands
from client.commands.acmd.standalone import ifconfig as module
from client.commands.runtime.catalog import CommandCatalog
from client.commands.runtime.hosts import (
    MacCommands, WindowsCommands, LinuxCommands, iOSCommands,
)
from client.commands.shell.runner import ShellCommandRunner


SAMPLE = [
    {'name': 'wlan0', 'ip': ['192.168.10.4'], 'ipv6': ['2001:db8::1', 'fe80::1%wlan0'], 'mac': '02:03:04:05:06:07', 'up': True},
    {'name': 'lo', 'ip': ['127.0.0.1'], 'ipv6': ['::1'], 'mac': '', 'up': True},
    {'name': 'docker0', 'ip': ['172.17.0.1'], 'mac': '02:42:10:00:00:01', 'up': True},
    {'name': 'eth1', 'ip': ['10.1.1.2', '169.254.3.4'], 'mac': 'A-B-C-D-E-F', 'up': True},
    {'name': 'en3', 'ip': ['192.168.3.1'], 'mac': '', 'up': False},
    {'name': 'eth2', 'ip': [], 'mac': '', 'up': True},
    {'name': 'unknown0', 'ip': [], 'ipv6': ['fe80::abcd%unknown0'], 'mac': '', 'up': None},
]


@pytest.mark.parametrize('alias,cls', [
    ('mac', MacCommands), ('win', WindowsCommands),
    ('linux', LinuxCommands), ('ios', iOSCommands),
])
def test_registered_on_all_four_platforms_and_removed_from_shell(alias, cls):
    # One Common registration for all four hosts, including iOS.
    assert ACMDNetworkCommands.__dict__['ifconfig'] is module.ifconfig
    assert 'ifconfig' not in iOSCommands.__bases__[1].__dict__
    assert cls.ifconfig is module.ifconfig
    assert getattr(cls.ifconfig, 'help', None) is None  # ACMD, not Shell.
    registry = ArgumentCommandRegistry(cls(None))
    assert registry.has_command('ifconfig')
    assert registry._entries['ifconfig']['spec'] is module.IFCONFIG_ARGUMENT_SPEC
    catalog = CommandCatalog(None)
    catalog._get_platform_name = lambda: alias
    shell_names = catalog.get_exported_shell_commands()
    assert 'ifconfig' not in shell_names
    manifest = catalog.get_command_manifest_payload()
    assert 'ifconfig' not in [item['name'] for item in manifest]
    assert len([item for item in manifest if item['name'] == 'acmd ifconfig']) == 1
    assert ShellCommandRunner(SimpleNamespace())._resolve_builtin_command(cls(None), 'ifconfig') is None


def test_default_is_original_three_column_filter_and_sort():
    assert module._display_rows(SAMPLE) == [
        {'name': 'eth1', 'ip': '10.1.1.2', 'mac': '0a:0b:0c:0d:0e:0f'},
        {'name': 'wlan0', 'ip': '192.168.10.4', 'mac': '02:03:04:05:06:07'},
    ]


def test_all_includes_down_tunnels_and_ipv6_with_native_up_values():
    rows = module._display_rows(SAMPLE, include_all=True)
    assert len(rows) == len(SAMPLE)
    assert list(rows[0]) == ['name', 'ip', 'ipv6', 'mac', 'up']
    by_name = {row['name']: row for row in rows}
    assert by_name['lo']['ipv6'] == '::1'
    assert by_name['docker0']['ip'] == '172.17.0.1'
    assert by_name['en3']['up'] is False
    assert by_name['eth2']['ip'] == ''
    assert by_name['wlan0']['ipv6'] == '2001:db8::1, fe80::1%wlan0'
    assert by_name['unknown0']['up'] is None
    assert all(len(row) == 5 and 'virtual' not in row and 'enabled' not in row for row in rows)


def test_interface_exact_match_and_all_combinations():
    assert [row['name'] for row in module._display_rows(
        SAMPLE, interface='wlan0',
    )] == ['wlan0']
    assert module._display_rows(SAMPLE, interface='WLAN0') == []
    assert module._display_rows(SAMPLE, interface='en3') == []
    assert [row['name'] for row in module._display_rows(
        SAMPLE, interface='en3', include_all=True,
    )] == ['en3']


@pytest.mark.parametrize('host', [MacCommands, WindowsCommands, LinuxCommands])
def test_desktop_acmd_json_alias_help_and_validation(monkeypatch, host):
    monkeypatch.setattr(module, 'collect_desktop_interfaces', lambda: SAMPLE)
    registry = ArgumentCommandRegistry(host(None))
    ok, text = registry.execute({'name': 'ifconfig', 'args': {}})
    assert ok == 1
    assert 'name' in text and 'mac' in text
    assert 'virtual' not in text and 'up' not in text

    ok, text = registry.execute({'name': 'ifconfig', 'args': {'a': True, 'json': True}})
    assert ok == 1
    records = json.loads(text)
    assert len(records) == len(SAMPLE)
    assert list(records[0]) == ['name', 'ip', 'ipv6', 'mac', 'up']
    assert next(item for item in records if item['name'] == 'en3')['up'] is False
    assert next(item for item in records if item['name'] == 'unknown0')['up'] is None
    assert next(item for item in records if item['name'] == 'wlan0')['up'] is True
    assert 'virtual' not in text and 'enabled' not in text

    ok, text = registry.execute({'name': 'ifconfig', 'args': {'i': 'wlan0', 'json': True}})
    assert ok == 1
    assert [row['name'] for row in json.loads(text)] == ['wlan0']
    assert list(json.loads(text)[0]) == ['name', 'ip', 'mac']

    ok, help_text = registry.execute({'name': 'ifconfig', 'args': {'h': True}})
    assert ok == 1
    assert '--all' in help_text and '--interface' in help_text
    assert '--json' in help_text and '--help' in help_text
    assert 'IPv6' in help_text and 'up status' in help_text

    ok, text = registry.execute({'name': 'ifconfig', 'args': {'unknown': True}})
    assert ok == 0 and 'unknown' in text.lower()

    ok, text = registry.execute({'name': 'ifconfig', 'args': {'i': 'not-present'}})
    assert ok == 0 and 'No useful network interfaces found' in text


def test_ios_uses_native_collector_for_default_and_all(monkeypatch):
    calls = []
    monkeypatch.setattr(module, 'collect_ios_interfaces', lambda: calls.append('ios') or SAMPLE)
    monkeypatch.setattr(module, 'collect_desktop_interfaces', lambda: (_ for _ in ()).throw(
        AssertionError('desktop collector used on iOS')
    ))
    registry = ArgumentCommandRegistry(iOSCommands(None))
    assert registry.execute({'name': 'ifconfig', 'args': {}})[0] == 1
    assert registry.execute({'name': 'ifconfig', 'args': {'all': True}})[0] == 1
    assert calls == ['ios', 'ios']


def test_desktop_psutil_reads_all_interfaces_and_status(monkeypatch):
    # Status-only interfaces should also be visible under --all.
    fake = SimpleNamespace(
        AF_LINK=18,
        net_if_addrs=lambda: {
            'eth0': [SimpleNamespace(family=socket.AF_INET, address='10.4.5.6'),
                     SimpleNamespace(family=socket.AF_INET6, address='fe80::1%eth0'),
                     SimpleNamespace(family=socket.AF_INET6, address='2001:db8::a'),
                     SimpleNamespace(family=socket.AF_INET6, address='fe80::1%eth0'),
                     SimpleNamespace(family=18, address='aa-bb-cc-dd-ee-ff')],
            'lo': [SimpleNamespace(family=socket.AF_INET, address='127.0.0.1')],
        },
        net_if_stats=lambda: {
            'eth0': SimpleNamespace(isup=True),
            'lo': SimpleNamespace(isup=True),
            'noaddr0': SimpleNamespace(isup=False),
        },
    )
    import sys
    monkeypatch.setitem(sys.modules, 'psutil', fake)
    rows = module.collect_desktop_interfaces()
    assert len(rows) == 3
    by_name = {item['name']: item for item in rows}
    assert by_name['eth0']['mac'] == 'aa:bb:cc:dd:ee:ff'
    assert by_name['eth0']['ip'] == ['10.4.5.6']
    assert by_name['eth0']['ipv6'] == ['fe80::1%eth0', '2001:db8::a']
    assert by_name['noaddr0']['up'] is False
    assert by_name['noaddr0']['ip'] == []
    assert by_name['noaddr0']['ipv6'] == []


def test_text_all_up_tristate_and_default_unchanged(monkeypatch):
    monkeypatch.setattr(module, 'collect_desktop_interfaces', lambda: SAMPLE)
    host = SimpleNamespace(command_platform='linux')
    ok, text = module.ifconfig(host, {'all': True})
    assert ok == 1
    assert 'ipv6' in text and 'up' in text
    assert 'unknown0' in text and '?' in text
    assert 'en3' in text and 'no' in text
    assert 'wlan0' in text and 'yes' in text
    assert 'virtual' not in text and 'enabled' not in text
    ok, default_text = module.ifconfig(host, {})
    assert ok == 1
    assert 'ipv6' not in default_text and 'up' not in default_text
    assert 'wlan0' in default_text and 'unknown0' not in default_text


def test_empty_result_reports_error(monkeypatch):
    monkeypatch.setattr(module, 'collect_desktop_interfaces', lambda: [])
    result = module.ifconfig(SimpleNamespace(command_platform='mac'), {'all': False})
    assert result == (0, 'Failed to get network interfaces: No useful network interfaces found')


def test_ios_getifaddrs_mac_and_down_interface(monkeypatch):
    """Exercise the iOS ctypes layout and ensure freeifaddrs runs."""
    class Node(ctypes.Structure):
        pass

    Node._fields_ = [
        ('next', ctypes.POINTER(Node)), ('name', ctypes.c_char_p),
        ('flags', ctypes.c_uint), ('addr', ctypes.c_void_p),
        ('netmask', ctypes.c_void_p), ('dstaddr', ctypes.c_void_p),
        ('data', ctypes.c_void_p),
    ]
    nodes = (Node * 5)()
    ip = ctypes.create_string_buffer(16)
    ip[0] = b'\x10'[0]
    ip[1] = socket.AF_INET
    ctypes.memmove(ctypes.addressof(ip) + 4, socket.inet_aton('10.1.2.3'), 4)
    link = ctypes.create_string_buffer(17)
    link[0] = 17
    link[1] = 18
    link[5] = 3  # 'en0'
    link[6] = 6
    ctypes.memmove(ctypes.addressof(link) + 8, b'en0\xaa\xbb\xcc\xdd\xee\xff', 9)
    nodes[0].name, nodes[0].flags, nodes[0].addr = b'en0', 1, ctypes.addressof(ip)
    nodes[1].name, nodes[1].flags, nodes[1].addr = b'en0', 1, ctypes.addressof(link)
    nodes[2].name, nodes[2].flags = b'utun0', 0
    ipv6 = ctypes.create_string_buffer(28)
    ipv6[0] = 28
    ipv6[1] = socket.AF_INET6
    # Darwin may embed interface index 4 in link-local address bytes 2-3.
    raw_ipv6 = bytearray(socket.inet_pton(socket.AF_INET6, 'fe80::aabb'))
    raw_ipv6[2:4] = (4).to_bytes(2, 'big')
    ctypes.memmove(ctypes.addressof(ipv6) + 8, bytes(raw_ipv6), 16)
    ctypes.memmove(ctypes.addressof(ipv6) + 24, ctypes.byref(ctypes.c_uint32(4)), 4)
    nodes[3].name, nodes[3].flags, nodes[3].addr = b'en0', 1, ctypes.addressof(ipv6)
    global_ipv6 = ctypes.create_string_buffer(28)
    global_ipv6[0] = 28
    global_ipv6[1] = socket.AF_INET6
    ctypes.memmove(ctypes.addressof(global_ipv6) + 8,
                   socket.inet_pton(socket.AF_INET6, '2001:db8::abcd'), 16)
    nodes[4].name, nodes[4].flags, nodes[4].addr = b'utun0', 0, ctypes.addressof(global_ipv6)
    nodes[0].next = ctypes.pointer(nodes[1])
    nodes[1].next = ctypes.pointer(nodes[2])
    nodes[2].next = ctypes.pointer(nodes[3])
    nodes[3].next = ctypes.pointer(nodes[4])

    class Function:
        def __init__(self, fn):
            self.fn = fn
        def __call__(self, *args):
            return self.fn(*args)

    freed = []

    def getifaddrs(out):
        ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(Node)))[0] = ctypes.pointer(nodes[0])
        return 0

    monkeypatch.setattr(module.ctypes, 'CDLL', lambda *_a: SimpleNamespace(
        getifaddrs=Function(getifaddrs), freeifaddrs=Function(lambda *_a: freed.append(1)),
    ))
    rows = module.collect_ios_interfaces()
    assert rows == [
        {'name': 'en0', 'ip': ['10.1.2.3'], 'ipv6': ['fe80::aabb%en0'], 'mac': 'aa:bb:cc:dd:ee:ff', 'up': True},
        {'name': 'utun0', 'ip': [], 'ipv6': ['2001:db8::abcd'], 'mac': '', 'up': False},
    ]
    assert freed == [1]


def test_common_network_owner_is_shared_and_netstat_stays_desktop_only():
    from client.commands.acmd.platform.ios import iOSACMDCommands

    assert 'ifconfig' not in iOSACMDCommands.__dict__
    assert ACMDNetworkCommands in iOSCommands.__mro__
    assert ACMDNetworkCommands.__dict__['ifconfig'] is module.ifconfig
    for alias, host in (
        ('mac', MacCommands), ('win', WindowsCommands),
        ('linux', LinuxCommands), ('ios', iOSCommands),
    ):
        reg = ArgumentCommandRegistry(host(None))
        assert reg.has_command('ifconfig')
        assert reg.has_command('netstat') is (alias != 'ios')
        names = {item['name'] for item in reg.get_manifest_payload()}
        assert 'acmd ifconfig' in names
        assert ('acmd netstat' in names) is (alias != 'ios')
        assert ('netstat' in reg.help_builder.build_command_list(reg.list_command_entries())) is (alias != 'ios')
        if alias == 'ios':
            assert reg.execute({'name': 'netstat', 'args': {}})[0] == 0


def test_acmd_platform_metadata_normalizes_aliases_and_rejects_invalid():
    from client.commands.acmd.decorators import argument_command

    @argument_command('probe', platforms=('darwin', 'WINDOWS', 'darwin'))
    def probe(self, args_dict):
        return 1, 'yes'

    assert probe.argument_command_platforms == ('mac', 'win')
    with pytest.raises(TypeError):
        argument_command('probe', platforms='mac')
    with pytest.raises(ValueError):
        argument_command('probe', platforms=[])
    with pytest.raises(ValueError):
        argument_command('probe', platforms=('freebsd',))
