"""Pythonista iOS dashboard snapshot; imported only for an iOS monitor session."""

import ctypes
import os
import socket
import time


# Library enumeration is substantially more expensive than the 5-second device metrics.
_LIBRARY_COUNT_TTL_SECONDS = 120
_library_counts_cache = {}


def _safe(func, default=None):
    try:
        result = func()
        return default if result is None else result
    except Exception:
        return default


def _ios_volume_capacity():
    """Read iOS Data Volume capacities reported for important usage."""
    from objc_util import ns, nsurl

    available_key = 'NSURLVolumeAvailableCapacityForImportantUsageKey'
    total_key = 'NSURLVolumeTotalCapacityKey'
    values = nsurl(os.path.expanduser('~/Documents')).resourceValuesForKeys_error_(
        ns([available_key, total_key]), None)
    if values is None:
        return {'free': None, 'total': None}

    def read_bytes(key):
        value = values.objectForKey_(key)
        return int(value.longLongValue()) if value is not None else None

    return {
        'free': _safe(lambda: read_bytes(available_key)),
        'total': _safe(lambda: read_bytes(total_key)),
    }


def _system_memory():
    """Return whole-device VM counters via Mach, using the same available-memory
    convention as macOS psutil (free + inactive). No external modules required.
    """
    class VMStatistics(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint32) for name in (
            'free_count', 'active_count', 'inactive_count', 'wire_count',
            'zero_fill_count', 'reactivations', 'pageins', 'pageouts',
            'faults', 'cow_faults', 'lookups', 'hits', 'purgeable_count',
            'purges', 'speculative_count',
        )]

    lib = ctypes.CDLL(None)
    host_self = lib.mach_host_self
    host_self.argtypes = []
    host_self.restype = ctypes.c_uint32
    host = host_self()
    vm = VMStatistics()
    count = ctypes.c_uint32(ctypes.sizeof(vm) // ctypes.sizeof(ctypes.c_uint32))
    host_stats = lib.host_statistics
    host_stats.argtypes = [ctypes.c_uint32, ctypes.c_int32,
                           ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_uint32)]
    host_stats.restype = ctypes.c_int32
    status = host_stats(host, 2, ctypes.cast(ctypes.byref(vm), ctypes.POINTER(ctypes.c_int32)), ctypes.byref(count))
    if status != 0:
        raise OSError('host_statistics(HOST_VM_INFO) returned %s' % status)

    page_size = ctypes.c_uint32()
    get_page_size = lib.host_page_size
    get_page_size.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    get_page_size.restype = ctypes.c_int32
    if get_page_size(host, ctypes.byref(page_size)) != 0 or page_size.value == 0:
        page_size.value = int(os.sysconf('SC_PAGE_SIZE'))
    page = int(page_size.value)
    return {
        'free': int(vm.free_count) * page,
        'inactive': int(vm.inactive_count) * page,
        'active': int(vm.active_count) * page,
        'wired': int(vm.wire_count) * page,
    }


def _process_resident_memory():
    """Pythonista process resident bytes, rather than Python heap size."""
    class TimeValue(ctypes.Structure):
        _fields_ = [('seconds', ctypes.c_int32), ('microseconds', ctypes.c_int32)]

    class TaskBasicInfo(ctypes.Structure):
        _fields_ = [('virtual_size', ctypes.c_uint64), ('resident_size', ctypes.c_uint64),
                    ('resident_size_max', ctypes.c_uint64), ('user_time', TimeValue),
                    ('system_time', TimeValue), ('policy', ctypes.c_int32),
                    ('suspend_count', ctypes.c_int32)]

    lib = ctypes.CDLL(None)
    task_self = lib.mach_task_self
    task_self.argtypes = []
    task_self.restype = ctypes.c_uint32
    info = TaskBasicInfo()
    count = ctypes.c_uint32(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint32))
    task_info = lib.task_info
    task_info.argtypes = [ctypes.c_uint32, ctypes.c_int32,
                          ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_uint32)]
    task_info.restype = ctypes.c_int32
    if task_info(task_self(), 20, ctypes.cast(ctypes.byref(info), ctypes.POINTER(ctypes.c_int32)),
                 ctypes.byref(count)) != 0:
        return None
    return int(info.resident_size)


def _photo_count():
    """Count accessible image assets without loading all photos into Python."""
    from objc_util import NSBundle, ObjCClass
    NSBundle.bundleWithPath_('/System/Library/Frameworks/Photos.framework').load()
    library = ObjCClass('PHPhotoLibrary')
    # 0: not determined, 1: restricted, 2: denied, 3: authorized, 4: limited.
    if int(library.authorizationStatus()) not in (3, 4):
        return None
    return int(ObjCClass('PHAsset').fetchAssetsWithMediaType_options_(1, None).count())


def _music_count():
    from objc_util import NSBundle, ObjCClass
    NSBundle.bundleWithPath_('/System/Library/Frameworks/MediaPlayer.framework').load()
    # No permission prompt from the monitor worker; retain an unavailable value.
    if int(ObjCClass('MPMediaLibrary').authorizationStatus()) != 3:
        return None
    items = ObjCClass('MPMediaQuery').songsQuery().items()
    return int(items.count()) if items is not None else 0


def _contacts_count():
    """Reuse the container-based Contacts query used by listcontacts, fetching IDs only."""
    from objc_util import ObjCClass, ns
    store_cls = ObjCClass('CNContactStore')
    if int(store_cls.authorizationStatusForEntityType_(0)) != 3:
        return None
    store = store_cls.alloc().init()
    contacts_cls = ObjCClass('CNContact')
    containers = store.containersMatchingPredicate_error_(None, None)
    identifiers = set()
    if containers is None:
        return None
    for i in range(int(containers.count())):
        container_id = str(containers.objectAtIndex_(i).identifier())
        predicate = contacts_cls.predicateForContactsInContainerWithIdentifier_(container_id)
        contacts = store.unifiedContactsMatchingPredicate_keysToFetch_error_(predicate, ns(['identifier']), None)
        if contacts is None:
            return None
        for j in range(int(contacts.count())):
            identifiers.add(str(contacts.objectAtIndex_(j).identifier()))
    return len(identifiers)


def _cached_count(key, collector):
    now = time.monotonic()
    cached = _library_counts_cache.get(key)
    if cached and now - cached[0] < _LIBRARY_COUNT_TTL_SECONDS:
        return cached[1]
    result = _safe(collector)
    _library_counts_cache[key] = (time.monotonic(), result)
    return result


def _interfaces():
    """Read IPv4 interface addresses via Darwin getifaddrs (no psutil)."""
    class Sockaddr(ctypes.Structure):
        _fields_ = [('len', ctypes.c_uint8), ('family', ctypes.c_uint8), ('data', ctypes.c_byte * 14)]

    class SockaddrIn(ctypes.Structure):
        _fields_ = [('len', ctypes.c_uint8), ('family', ctypes.c_uint8),
                    ('port', ctypes.c_uint16), ('address', ctypes.c_ubyte * 4),
                    ('zero', ctypes.c_byte * 8)]

    class IfAddrs(ctypes.Structure):
        pass

    IfAddrs._fields_ = [('next', ctypes.POINTER(IfAddrs)), ('name', ctypes.c_char_p),
                        ('flags', ctypes.c_uint), ('addr', ctypes.POINTER(Sockaddr)),
                        ('netmask', ctypes.POINTER(Sockaddr)),
                        ('dstaddr', ctypes.POINTER(Sockaddr)), ('data', ctypes.c_void_p)]
    lib = ctypes.CDLL(None)
    lib.getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(IfAddrs))]
    lib.getifaddrs.restype = ctypes.c_int
    lib.freeifaddrs.argtypes = [ctypes.POINTER(IfAddrs)]
    head = ctypes.POINTER(IfAddrs)()
    if lib.getifaddrs(ctypes.byref(head)) != 0:
        return []
    result = []
    try:
        entry = head
        while entry:
            current = entry.contents
            if current.addr and current.addr.contents.family == socket.AF_INET and current.name:
                name = current.name.decode('utf-8', 'replace')
                address = ctypes.cast(current.addr, ctypes.POINTER(SockaddrIn)).contents
                value = socket.inet_ntoa(bytes(address.address))
                if name == 'en0' or name.startswith('pdp_ip'):
                    pair = {'name': name, 'ip': value}
                    if pair not in result:
                        result.append(pair)
            entry = current.next
    finally:
        lib.freeifaddrs(head)
    return result[:5]


def _route_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]


def collect_ios_dashboard():
    """Read each iOS metric independently; restricted libraries return null counts."""
    from objc_util import ObjCClass

    proc = _safe(lambda: ObjCClass('NSProcessInfo').processInfo())
    device = _safe(lambda: ObjCClass('UIDevice').currentDevice())
    screen = _safe(lambda: ObjCClass('UIScreen').mainScreen())
    _safe(lambda: device.setBatteryMonitoringEnabled_(True))

    battery_level = _safe(lambda: float(device.batteryLevel()), -1)
    battery_state = _safe(lambda: int(device.batteryState()), 0)
    thermal_state = _safe(lambda: int(proc.thermalState()))
    bounds = _safe(lambda: screen.bounds())
    native_bounds = _safe(lambda: screen.nativeBounds())
    disk = _safe(_ios_volume_capacity, {'free': None, 'total': None})
    audio = _safe(lambda: ObjCClass('AVAudioSession').sharedInstance())

    def audio_route():
        outputs = audio.currentRoute().outputs()
        return ', '.join(str(outputs.objectAtIndex_(i).portName()) for i in range(outputs.count()))

    physical_total = _safe(lambda: int(proc.physicalMemory()))
    vm = _safe(_system_memory)
    available = min(physical_total, vm['free'] + vm['inactive']) if vm and physical_total else None
    memory_used = max(0, physical_total - available) if available is not None else None
    return {
        'cpu': {
            'active': _safe(lambda: int(proc.activeProcessorCount())),
            'total': _safe(lambda: int(proc.processorCount())),
        },
        'memory_total': physical_total,
        'memory': {
            'total': physical_total,
            'used': memory_used,
            'available': available,
            'percent': round(memory_used / physical_total * 100, 1) if memory_used is not None and physical_total else None,
            'active': vm['active'] if vm else None,
            'wired': vm['wired'] if vm else None,
            'inactive': vm['inactive'] if vm else None,
            'free': vm['free'] if vm else None,
            'app_resident': _safe(_process_resident_memory),
        },
        'disk': disk,
        'screen': {
            'pixels': _safe(lambda: [round(native_bounds.size.width), round(native_bounds.size.height)]) if native_bounds else None,
            'points': _safe(lambda: [round(bounds.size.width), round(bounds.size.height)]) if bounds else None,
            'scale': _safe(lambda: float(screen.scale())),
            'brightness': _safe(lambda: round(float(screen.brightness()) * 100)),
        },
        'battery': {
            'percent': round(battery_level * 100) if battery_level is not None and battery_level >= 0 else None,
            'state': {0: 'Unknown', 1: 'Unplugged', 2: 'Charging', 3: 'Full'}.get(battery_state, 'Unknown'),
        },
        'low_power': _safe(lambda: bool(proc.isLowPowerModeEnabled())),
        'thermal': {0: 'Nominal', 1: 'Fair', 2: 'Serious', 3: 'Critical'}.get(thermal_state, 'Unknown') if thermal_state is not None else None,
        'uptime_seconds': _safe(lambda: float(proc.systemUptime())),
        'audio': {
            'sample_rate': _safe(lambda: float(audio.sampleRate())) if audio else None,
            'output_latency_ms': _safe(lambda: round(float(audio.outputLatency()) * 1000, 1)) if audio else None,
            'output': _safe(audio_route) if audio else None,
            'volume_percent': _safe(lambda: round(float(audio.outputVolume()) * 100)) if audio else None,
        },
        'network': {
            'route_ip': _safe(_route_ip),
            'interfaces': _safe(_interfaces, []),
        },
        'library': {
            'photos': _cached_count('photos', _photo_count),
            'music': _cached_count('music', _music_count),
            'contacts': _cached_count('contacts', _contacts_count),
        },
    }
