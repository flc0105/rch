import ctypes
import socket


from core.utils.network import normalize_mac_address
class GetifaddrsIfconfigProvider:
    """
    iOS / macOS / Linux network interface provider based on libc.getifaddrs.

    只走 getifaddrs。
    不 fallback。
    不套 shell。
    """

    IFF_UP = 0x1
    AF_LINK = 18
    AF_PACKET = 17

    def __init__(self, platform_alias):
        self.platform_alias = platform_alias

    def collect(self):
        if self.platform_alias not in ('ios', 'mac', 'linux'):
            raise RuntimeError(
                'getifaddrs provider does not support {}'.format(
                    self.platform_alias
                )
            )

        libc = ctypes.CDLL(None)

        class SockaddrDarwin(ctypes.Structure):
            _fields_ = [
                ('sa_len', ctypes.c_uint8),
                ('sa_family', ctypes.c_uint8),
                ('sa_data', ctypes.c_char * 14),
            ]

        class SockaddrLinux(ctypes.Structure):
            _fields_ = [
                ('sa_family', ctypes.c_ushort),
                ('sa_data', ctypes.c_char * 14),
            ]

        class SockaddrInDarwin(ctypes.Structure):
            _fields_ = [
                ('sin_len', ctypes.c_uint8),
                ('sin_family', ctypes.c_uint8),
                ('sin_port', ctypes.c_uint16),
                ('sin_addr', ctypes.c_ubyte * 4),
                ('sin_zero', ctypes.c_char * 8),
            ]

        class SockaddrInLinux(ctypes.Structure):
            _fields_ = [
                ('sin_family', ctypes.c_ushort),
                ('sin_port', ctypes.c_uint16),
                ('sin_addr', ctypes.c_ubyte * 4),
                ('sin_zero', ctypes.c_char * 8),
            ]

        class SockaddrDl(ctypes.Structure):
            """
            Darwin / iOS AF_LINK sockaddr_dl.

            MAC 地址在：
            sdl_data[sdl_nlen : sdl_nlen + sdl_alen]
            """
            _fields_ = [
                ('sdl_len', ctypes.c_uint8),
                ('sdl_family', ctypes.c_uint8),
                ('sdl_index', ctypes.c_uint16),
                ('sdl_type', ctypes.c_uint8),
                ('sdl_nlen', ctypes.c_uint8),
                ('sdl_alen', ctypes.c_uint8),
                ('sdl_slen', ctypes.c_uint8),
                ('sdl_data', ctypes.c_ubyte * 12),
            ]

        class SockaddrLl(ctypes.Structure):
            """
            Linux AF_PACKET sockaddr_ll.
            """
            _fields_ = [
                ('sll_family', ctypes.c_ushort),
                ('sll_protocol', ctypes.c_ushort),
                ('sll_ifindex', ctypes.c_int),
                ('sll_hatype', ctypes.c_ushort),
                ('sll_pkttype', ctypes.c_ubyte),
                ('sll_halen', ctypes.c_ubyte),
                ('sll_addr', ctypes.c_ubyte * 8),
            ]

        class IfAddrs(ctypes.Structure):
            pass

        IfAddrs._fields_ = [
            ('ifa_next', ctypes.POINTER(IfAddrs)),
            ('ifa_name', ctypes.c_char_p),
            ('ifa_flags', ctypes.c_uint),
            ('ifa_addr', ctypes.c_void_p),
            ('ifa_netmask', ctypes.c_void_p),
            ('ifa_dstaddr', ctypes.c_void_p),
            ('ifa_data', ctypes.c_void_p),
        ]

        getifaddrs = libc.getifaddrs
        getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(IfAddrs))]
        getifaddrs.restype = ctypes.c_int

        freeifaddrs = libc.freeifaddrs
        freeifaddrs.argtypes = [ctypes.POINTER(IfAddrs)]
        freeifaddrs.restype = None

        addrs = ctypes.POINTER(IfAddrs)()

        if getifaddrs(ctypes.byref(addrs)) != 0:
            raise RuntimeError('getifaddrs failed')

        interfaces = {}

        try:
            cursor = addrs

            while cursor:
                item = cursor.contents
                cursor = item.ifa_next

                if not item.ifa_name or not item.ifa_addr:
                    continue

                if not self._is_interface_up(item.ifa_flags):
                    continue

                name = item.ifa_name.decode('utf-8', 'replace')

                entry = interfaces.setdefault(name, {
                    'name': name,
                    'ip': [],
                    'mac': '',
                })

                if self.platform_alias in ('ios', 'mac'):
                    family = int(ctypes.cast(
                        item.ifa_addr,
                        ctypes.POINTER(SockaddrDarwin),
                    ).contents.sa_family)
                else:
                    family = int(ctypes.cast(
                        item.ifa_addr,
                        ctypes.POINTER(SockaddrLinux),
                    ).contents.sa_family)

                if family == socket.AF_INET:
                    if self.platform_alias in ('ios', 'mac'):
                        sockaddr_in = ctypes.cast(
                            item.ifa_addr,
                            ctypes.POINTER(SockaddrInDarwin),
                        ).contents
                    else:
                        sockaddr_in = ctypes.cast(
                            item.ifa_addr,
                            ctypes.POINTER(SockaddrInLinux),
                        ).contents

                    ip = socket.inet_ntoa(bytes(sockaddr_in.sin_addr))

                    if ip and ip not in entry['ip']:
                        entry['ip'].append(ip)

                elif self.platform_alias in ('ios', 'mac') and family == self.AF_LINK:
                    sockaddr_dl = ctypes.cast(
                        item.ifa_addr,
                        ctypes.POINTER(SockaddrDl),
                    ).contents

                    start = int(sockaddr_dl.sdl_nlen)
                    end = start + int(sockaddr_dl.sdl_alen)

                    mac = self._format_mac_bytes(
                        bytes(sockaddr_dl.sdl_data)[start:end]
                    )

                    if mac:
                        entry['mac'] = mac

                elif self.platform_alias == 'linux' and family == self.AF_PACKET:
                    sockaddr_ll = ctypes.cast(
                        item.ifa_addr,
                        ctypes.POINTER(SockaddrLl),
                    ).contents

                    mac = self._format_mac_bytes(
                        bytes(sockaddr_ll.sll_addr[:sockaddr_ll.sll_halen])
                    )

                    if mac:
                        entry['mac'] = mac

        finally:
            freeifaddrs(addrs)

        return list(interfaces.values())

    def _is_interface_up(self, flags):
        try:
            return bool(int(flags) & self.IFF_UP)
        except Exception:
            return False

    def _format_mac_bytes(self, value):
        data = bytes(value or b'')

        if len(data) != 6:
            return ''

        if data == b'\x00\x00\x00\x00\x00\x00':
            return ''

        return ':'.join('{:02x}'.format(part) for part in data)


class WindowsPsutilIfconfigProvider:
    """
    Windows network interface provider based on psutil only.

    不调用 ipconfig。
    不调用 netsh。
    不套 shell。
    """

    def collect(self):
        try:
            import psutil
        except Exception as e:
            raise RuntimeError('psutil is required on Windows: {}'.format(e))

        try:
            all_addrs = psutil.net_if_addrs()
            all_stats = psutil.net_if_stats()
        except Exception as e:
            raise RuntimeError(
                'psutil failed to read network interfaces: {}'.format(e)
            )

        if not all_addrs:
            raise RuntimeError('psutil returned no network interfaces')

        rows = []

        for name, addrs in all_addrs.items():
            stats = all_stats.get(name)

            if stats is not None and not getattr(stats, 'isup', False):
                continue

            item = {
                'name': name,
                'ip': [],
                'mac': '',
            }

            for addr in addrs or []:
                family = getattr(addr, 'family', None)
                address = str(getattr(addr, 'address', '') or '').strip()

                if not address:
                    continue

                if self._is_ipv4_family(family):
                    if address not in item['ip']:
                        item['ip'].append(address)
                    continue

                if self._is_mac_family(family, psutil):
                    mac = normalize_mac_address(address)

                    if mac:
                        item['mac'] = mac

            rows.append(item)

        return rows

    def _is_ipv4_family(self, family):
        try:
            return family == socket.AF_INET or int(family) == int(socket.AF_INET)
        except Exception:
            return False

    def _is_mac_family(self, family, psutil_module):
        candidates = [
            getattr(psutil_module, 'AF_LINK', None),
            getattr(socket, 'AF_LINK', None),
            getattr(socket, 'AF_PACKET', None),
        ]

        for candidate in candidates:
            if candidate is None:
                continue

            try:
                if family == candidate or int(family) == int(candidate):
                    return True
            except Exception:
                continue

        return False

