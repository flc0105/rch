"""Network interfaces: shared ACMD entry with desktop and iOS collectors."""

import ctypes
import socket

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, ResultDataShape, resolve_presentation, render_structured_result
from core.utils.network import normalize_mac_address


IFCONFIG_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='ifconfig',
    description='Show network interfaces',
    options=[
        ArgumentOptionSpec(
            name='all', option_type='flag', default=False, alias='a',
            help_text='Show all interfaces with IPv6 and up status (up does not imply connectivity)',
        ),
        ArgumentOptionSpec(
            name='interface', option_type='str', default='', alias='i',
            allow_empty=False, help_text='Match an interface name exactly',
        ),
        ArgumentOptionSpec('format', 'str', default='', alias='f',
                           choices=('table', 'records', 'json'), help_text='Supported output: table, records, json'),
        ArgumentOptionSpec(
            name='json', option_type='flag', default=False,
            help_text='Output as JSON',
        ),
        ArgumentOptionSpec(
            name='help', option_type='flag', default=False, alias='h',
            help_text='Show this help message',
        ),
    ],
    examples=[
        'acmd ifconfig',
        'acmd ifconfig --all',
        'acmd ifconfig -a --json',
        'acmd ifconfig --interface en0',
        'acmd ifconfig -i "Wi-Fi" --json',
    ],
)


# Preserve the established short output's interface filtering and priority order.
_IGNORED_PREFIXES = (
    'lo', 'docker', 'br-', 'bridge', 'veth', 'virbr', 'vmnet',
    'vboxnet', 'vethernet', 'utun', 'awdl', 'llw', 'anpi',
    'gif', 'stf', 'ipsec',
)
_IGNORED_PARTS = (
    'loopback', 'virtualbox', 'vmware', 'hyper-v', 'bluetooth',
    'thunderbolt bridge', 'tunnel', 'vpn',
)
_PRIORITY_PREFIXES = ('ethernet', 'en', 'eth', 'wi-fi', 'wifi', 'wlan', 'pdp_ip')


def collect_desktop_interfaces():
    """Return ordinary interface records from psutil on macOS/Windows/Linux."""
    import psutil

    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    if not addresses and not stats:
        raise RuntimeError('psutil returned no network interfaces')

    mac_families = {
        candidate for candidate in (
            getattr(psutil, 'AF_LINK', None),
            getattr(socket, 'AF_LINK', None),
            getattr(socket, 'AF_PACKET', None),
        ) if candidate is not None
    }
    records = []
    for name in dict.fromkeys((*addresses, *stats)):
        status = stats.get(name)
        record = {
            'name': name, 'ip': [], 'ipv6': [], 'mac': '',
            'up': None if status is None else bool(status.isup),
        }
        for address in addresses.get(name, ()):
            value = str(getattr(address, 'address', '') or '').strip()
            family = getattr(address, 'family', None)
            if family == socket.AF_INET and value and value not in record['ip']:
                record['ip'].append(value)
            elif family == socket.AF_INET6 and value and value not in record['ipv6']:
                record['ipv6'].append(value)
            elif family in mac_families:
                mac = normalize_mac_address(value)
                if mac:
                    record['mac'] = mac
        records.append(record)
    return records


def collect_ios_interfaces():
    """Return iOS interface records via libc.getifaddrs (no psutil import)."""
    class Sockaddr(ctypes.Structure):
        _fields_ = [
            ('length', ctypes.c_uint8), ('family', ctypes.c_uint8),
            ('data', ctypes.c_char * 14),
        ]

    class SockaddrIn(ctypes.Structure):
        _fields_ = [
            ('length', ctypes.c_uint8), ('family', ctypes.c_uint8),
            ('port', ctypes.c_uint16), ('addr', ctypes.c_ubyte * 4),
            ('padding', ctypes.c_char * 8),
        ]

    class SockaddrIn6(ctypes.Structure):
        _fields_ = [
            ('length', ctypes.c_uint8), ('family', ctypes.c_uint8),
            ('port', ctypes.c_uint16), ('flowinfo', ctypes.c_uint32),
            ('addr', ctypes.c_ubyte * 16), ('scope_id', ctypes.c_uint32),
        ]

    class SockaddrDlHeader(ctypes.Structure):
        _fields_ = [
            ('length', ctypes.c_uint8), ('family', ctypes.c_uint8),
            ('index', ctypes.c_uint16), ('type', ctypes.c_uint8),
            ('name_length', ctypes.c_uint8), ('address_length', ctypes.c_uint8),
            ('selector_length', ctypes.c_uint8),
        ]

    class IfAddrs(ctypes.Structure):
        pass

    IfAddrs._fields_ = [
        ('next', ctypes.POINTER(IfAddrs)), ('name', ctypes.c_char_p),
        ('flags', ctypes.c_uint), ('addr', ctypes.c_void_p),
        ('netmask', ctypes.c_void_p), ('dstaddr', ctypes.c_void_p),
        ('data', ctypes.c_void_p),
    ]

    libc = ctypes.CDLL(None)
    libc.getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(IfAddrs))]
    libc.getifaddrs.restype = ctypes.c_int
    libc.freeifaddrs.argtypes = [ctypes.POINTER(IfAddrs)]
    libc.freeifaddrs.restype = None

    head = ctypes.POINTER(IfAddrs)()
    if libc.getifaddrs(ctypes.byref(head)) != 0:
        raise OSError('getifaddrs failed')
    interfaces = {}
    try:
        cursor = head
        while cursor:
            node = cursor.contents
            cursor = node.next
            if not node.name:
                continue
            name = node.name.decode('utf-8', 'replace')
            record = interfaces.setdefault(name, {
                'name': name, 'ip': [], 'ipv6': [], 'mac': '',
                'up': bool(node.flags & 0x1),  # IFF_UP
            })
            if not node.addr:
                continue
            family = ctypes.cast(node.addr, ctypes.POINTER(Sockaddr)).contents.family
            if family == socket.AF_INET:
                ip = socket.inet_ntoa(bytes(
                    ctypes.cast(node.addr, ctypes.POINTER(SockaddrIn)).contents.addr
                ))
                if ip not in record['ip']:
                    record['ip'].append(ip)
            elif family == socket.AF_INET6:
                sockaddr = ctypes.cast(
                    node.addr, ctypes.POINTER(SockaddrIn6)
                ).contents
                raw = bytearray(sockaddr.addr)
                # Darwin may encode the interface index in bytes 2-3 of a
                # link-local IPv6 address. Remove it and use the name as zone.
                link_local = raw[0] == 0xfe and (raw[1] & 0xc0) == 0x80
                if link_local and (raw[2] or raw[3]):
                    raw[2:4] = b'\x00\x00'
                ip = socket.inet_ntop(socket.AF_INET6, bytes(raw))
                if link_local:
                    ip += f'%{name}'
                if ip not in record['ipv6']:
                    record['ipv6'].append(ip)
            elif family == 18:  # Darwin AF_LINK
                header = ctypes.cast(
                    node.addr, ctypes.POINTER(SockaddrDlHeader)
                ).contents
                # The sockaddr_dl name has variable length; its MAC follows the name.
                end = 8 + int(header.name_length) + int(header.address_length)
                if header.address_length == 6 and end <= header.length:
                    value = ctypes.string_at(
                        node.addr + 8 + int(header.name_length), 6,
                    )
                    record['mac'] = normalize_mac_address(value.hex())
    finally:
        libc.freeifaddrs(head)
    return list(interfaces.values())


def collect_interfaces(os_alias):
    """Select the native iOS or shared desktop collector."""
    if os_alias == 'ios':
        return collect_ios_interfaces()
    return collect_desktop_interfaces()


def _useful_ipv4(address):
    text = str(address or '').strip()
    if text in ('', '0.0.0.0') or text.startswith(('127.', '169.254.')):
        return False
    parts = text.split('.')
    return len(parts) == 4 and all(
        part.isdigit() and 0 <= int(part) <= 255 for part in parts
    )


def _useful_name(name):
    lower = str(name or '').strip().lower()
    return bool(lower) and not lower.startswith(_IGNORED_PREFIXES) and not any(
        token in lower for token in _IGNORED_PARTS
    )


def _sort_key(record):
    lower = record['name'].lower()
    for priority, prefix in enumerate(_PRIORITY_PREFIXES):
        if lower.startswith(prefix):
            return priority, lower
    return len(_PRIORITY_PREFIXES), lower


def _display_rows(records, *, include_all=False, interface=''):
    rows = []
    seen = set()
    for record in records:
        name = str(record.get('name') or '').strip()
        if not name or (interface and name != interface):
            continue
        up = record.get('up')
        if not include_all and (up is False or not _useful_name(name)):
            continue
        ips = []
        for address in record.get('ip') or ():
            address = str(address or '').strip()
            if (include_all or _useful_ipv4(address)) and address and address not in ips:
                ips.append(address)
        if not include_all and not ips:
            continue
        mac = normalize_mac_address(record.get('mac') or '')
        ipv6 = []
        if include_all:
            for address in record.get('ipv6') or ():
                address = str(address or '').strip()
                if address and address not in ipv6:
                    ipv6.append(address)
        key = (name, tuple(ips), tuple(ipv6), mac)
        if key in seen:
            continue
        seen.add(key)
        row = {'name': name, 'ip': ', '.join(ips)}
        if include_all:
            row['ipv6'] = ', '.join(ipv6)
        row['mac'] = mac
        if include_all:
            row['up'] = up
        rows.append(row)
    rows.sort(key=_sort_key)
    return rows


@argument_command('ifconfig', spec=IFCONFIG_ARGUMENT_SPEC)
def ifconfig(self, args_dict, payload=None):
    """Show interfaces; the collectors return data without command protocol types."""
    try:
        platform = self.command_platform
        interfaces = collect_interfaces(platform)
        all_interfaces = bool(args_dict.get('all', False))
        rows = _display_rows(
            interfaces,
            include_all=all_interfaces,
            interface=args_dict.get('interface') or '',
        )
        if not rows:
            raise RuntimeError(
                'No network interfaces found' if all_interfaces else
                'No useful network interfaces found'
            )
        output, layout = resolve_presentation(args_dict, ResultDataShape.TABLE)
        json_output = output == 'json'
        if all_interfaces and not json_output:
            for row in rows:
                up = row['up']
                row['up'] = '?' if up is None else 'yes' if up else 'no'
        return render_structured_result(
            StructuredCommandResult(status=1, data=rows, shape=layout),
            output_format=output,
        )
    except Exception as exc:
        return 0, f'Failed to get network interfaces: {exc}'
