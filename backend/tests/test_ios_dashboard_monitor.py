"""iOS monitor requires neither psutil nor changes to desktop monitoring."""

import builtins
import sys
import threading
import types

import pytest

from client.monitor.manager import DeviceMonitorManager
from core.protocol.monitor import normalize_monitor_channels, normalize_monitor_intervals


class Connection:
    def __init__(self):
        self.messages = []
        self.snapshot = threading.Event()

    def send(self, message):
        self.messages.append(message)
        if message['type'] == 'monitor_snapshot':
            self.snapshot.set()


def test_ios_channel_has_shared_default_interval():
    assert normalize_monitor_channels(['ios_dashboard']) == ['ios_dashboard']
    assert normalize_monitor_intervals(None, ['ios_dashboard']) == {'ios_dashboard': 5.0}


def test_ios_dashboard_session_skips_psutil(monkeypatch):
    from client.monitor import ios_dashboard
    conn = Connection()
    monitor = DeviceMonitorManager(conn)
    monitor._os_alias = 'ios'
    monkeypatch.setattr(ios_dashboard, 'collect_ios_dashboard', lambda: {'thermal': 'Nominal'})
    imported = []
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == 'psutil' and threading.current_thread().name.startswith('device-monitor'):
            imported.append(name)
            raise ImportError('psutil unavailable')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    monitor.open_session('ios-dashboard-test', channels=['ios_dashboard'])
    worker = next(iter(monitor._sessions.values()))['worker']
    try:
        assert conn.snapshot.wait(2), conn.messages
        assert not imported
        snapshot = next(m for m in conn.messages if m['type'] == 'monitor_snapshot')
        assert snapshot['channel'] == 'ios_dashboard'
        assert snapshot['data'] == {'thermal': 'Nominal'}
    finally:
        monitor.close_all_sessions(notify=False)
        worker.join(2)


def test_desktop_does_not_collect_ios_dashboard():
    monitor = DeviceMonitorManager(Connection())
    monitor._os_alias = 'win'
    with pytest.raises(ValueError, match='only available on iOS'):
        monitor._collect_channel('ios_dashboard', None, {})


def test_ios_collector_uses_pythonista_frameworks(monkeypatch):
    from client.monitor import ios_dashboard
    class Proc:
        def activeProcessorCount(self): return 6
        def processorCount(self): return 6
        def physicalMemory(self): return 8 * 1024 ** 3
        def isLowPowerModeEnabled(self): return False
        def thermalState(self): return 0
        def systemUptime(self): return 3600

    class Device:
        def setBatteryMonitoringEnabled_(self, flag): assert flag
        def batteryLevel(self): return 0.85
        def batteryState(self): return 2

    class Screen:
        def scale(self): return 3
        def brightness(self): return 0.65
        def bounds(self): return types.SimpleNamespace(size=types.SimpleNamespace(width=393, height=852))
        def nativeBounds(self): return types.SimpleNamespace(size=types.SimpleNamespace(width=1179, height=2556))

    class Audio:
        def sampleRate(self): return 48000
        def outputLatency(self): return 0.0154
        def currentRoute(self):
            return types.SimpleNamespace(outputs=lambda: types.SimpleNamespace(
                count=lambda: 1, objectAtIndex_=lambda i: types.SimpleNamespace(portName=lambda: 'Speaker')))

    objects = {'NSProcessInfo': types.SimpleNamespace(processInfo=lambda: Proc()),
               'UIDevice': types.SimpleNamespace(currentDevice=lambda: Device()),
               'UIScreen': types.SimpleNamespace(mainScreen=lambda: Screen()),
               'AVAudioSession': types.SimpleNamespace(sharedInstance=lambda: Audio())}
    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(ObjCClass=lambda name: objects[name]))
    monkeypatch.setattr(ios_dashboard, '_route_ip', lambda: '192.168.1.2')
    monkeypatch.setattr(ios_dashboard, '_interfaces', lambda: [{'name': 'en0', 'ip': '192.168.1.2'}])
    monkeypatch.setattr(ios_dashboard, '_ios_volume_capacity', lambda: {'free': 20, 'total': 100})
    data = ios_dashboard.collect_ios_dashboard()
    assert data['battery'] == {'percent': 85, 'state': 'Charging'}
    assert data['cpu']['active'] == 6
    assert data['disk'] == {'free': 20, 'total': 100}
    assert data['screen']['pixels'] == [1179, 2556]
    assert data['audio']['output'] == 'Speaker'
    assert data['network']['route_ip'] == '192.168.1.2'


def test_ios_dashboard_memory_and_counts_are_independent(monkeypatch):
    from client.monitor import ios_dashboard as collector
    collector._library_counts_cache.clear()
    class Proc:
        def physicalMemory(self): return 8 * 1024 ** 3
        def activeProcessorCount(self): return 6
        def processorCount(self): return 6
        def thermalState(self): return 1

    class Audio:
        def outputVolume(self): return 0.42
        def sampleRate(self): raise OSError('No sample rate')

    objects = {'NSProcessInfo': types.SimpleNamespace(processInfo=lambda: Proc()),
               'AVAudioSession': types.SimpleNamespace(sharedInstance=lambda: Audio())}
    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(ObjCClass=lambda name: objects[name]))
    monkeypatch.setattr(collector, '_system_memory', lambda: {
        'free': 1 * 1024 ** 3, 'inactive': 1 * 1024 ** 3,
        'active': 2 * 1024 ** 3, 'wired': 2 * 1024 ** 3,
    })
    monkeypatch.setattr(collector, '_process_resident_memory', lambda: 150 * 1024 ** 2)
    monkeypatch.setattr(collector, '_photo_count', lambda: 1234)
    monkeypatch.setattr(collector, '_music_count', lambda: (_ for _ in ()).throw(PermissionError('denied')))
    monkeypatch.setattr(collector, '_contacts_count', lambda: 55)
    monkeypatch.setattr(collector, '_route_ip', lambda: '192.168.1.2')
    monkeypatch.setattr(collector, '_interfaces', lambda: [])
    data = collector.collect_ios_dashboard()
    assert data['memory']['used'] == 6 * 1024 ** 3
    assert data['memory']['available'] == 2 * 1024 ** 3
    assert data['memory']['percent'] == 75.0
    assert data['memory']['app_resident'] == 150 * 1024 ** 2
    assert data['audio']['volume_percent'] == 42
    assert data['audio']['sample_rate'] is None
    assert data['thermal'] == 'Fair'
    assert data['library'] == {'photos': 1234, 'music': None, 'contacts': 55}


def test_library_counts_are_cached_and_retried_after_expiration(monkeypatch):
    from client.monitor import ios_dashboard as collector
    collector._library_counts_cache.clear()
    now = [1000.0]
    monkeypatch.setattr(collector.time, 'monotonic', lambda: now[0])
    calls = []
    def collect():
        calls.append(True)
        return 12
    assert collector._cached_count('photos', collect) == 12
    now[0] += 5
    assert collector._cached_count('photos', collect) == 12
    assert len(calls) == 1
    now[0] += collector._LIBRARY_COUNT_TTL_SECONDS
    assert collector._cached_count('photos', collect) == 12
    assert len(calls) == 2


def test_library_permissions_and_counts(monkeypatch):
    from client.monitor import ios_dashboard as collector
    class NSArray:
        def __init__(self, objects): self.objects = objects
        def count(self): return len(self.objects)
        def objectAtIndex_(self, i): return self.objects[i]

    class Contact:
        def __init__(self, identifier): self.value = identifier
        def identifier(self): return self.value

    class Store:
        @staticmethod
        def authorizationStatusForEntityType_(kind): assert kind == 0; return 3
        @staticmethod
        def alloc(): return Store()
        def init(self): return self
        def containersMatchingPredicate_error_(self, *args): return NSArray([Contact('a'), Contact('b')])
        def unifiedContactsMatchingPredicate_keysToFetch_error_(self, predicate, keys, error):
            return NSArray([Contact('a'), Contact('b')]) if predicate == 'a' else NSArray([Contact('b'), Contact('c')])

    class Media:
        @staticmethod
        def authorizationStatus(): return 3

    class Query:
        @staticmethod
        def songsQuery(): return types.SimpleNamespace(items=lambda: NSArray([1, 2, 3]))

    class Photos:
        @staticmethod
        def authorizationStatus(): return 4

    class Asset:
        @staticmethod
        def fetchAssetsWithMediaType_options_(kind, options):
            assert kind == 1
            return NSArray(list(range(10)))

    classes = {'CNContactStore': Store, 'CNContact': types.SimpleNamespace(
        predicateForContactsInContainerWithIdentifier_=lambda name: name),
        'MPMediaLibrary': Media, 'MPMediaQuery': Query, 'PHPhotoLibrary': Photos,
        'PHAsset': Asset}
    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(
        ObjCClass=lambda name: classes[name], ns=lambda value: value,
        NSBundle=types.SimpleNamespace(bundleWithPath_=lambda path: types.SimpleNamespace(load=lambda: True))))
    assert collector._contacts_count() == 3  # Same unified contact in multiple containers.
    assert collector._music_count() == 3
    assert collector._photo_count() == 10
    classes['PHPhotoLibrary'] = types.SimpleNamespace(authorizationStatus=lambda: 2)
    assert collector._photo_count() is None


def test_ios_vm_statistics_uses_page_size_and_host_counters(monkeypatch):
    import ctypes
    from client.monitor import ios_dashboard as collector

    def mach_host_self():
        return 1

    def host_statistics(host, flavor, stats_pointer, count_pointer):
        assert host == 1 and flavor == 2
        values = ctypes.cast(stats_pointer, ctypes.POINTER(ctypes.c_uint32))
        values[0], values[1], values[2], values[3] = 100, 200, 300, 400
        return 0

    def host_page_size(host, size_pointer):
        ctypes.cast(size_pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value = 16384
        return 0

    monkeypatch.setattr(collector.ctypes, 'CDLL', lambda _: types.SimpleNamespace(
        mach_host_self=mach_host_self,
        host_statistics=host_statistics,
        host_page_size=host_page_size,
    ))
    assert collector._system_memory() == {
        'free': 100 * 16384,
        'active': 200 * 16384,
        'inactive': 300 * 16384,
        'wired': 400 * 16384,
    }


def test_ios_volume_uses_verified_important_usage_capacity(monkeypatch):
    from client.monitor import ios_dashboard as collector

    important_key = 'NSURLVolumeAvailableCapacityForImportantUsageKey'
    total_key = 'NSURLVolumeTotalCapacityKey'
    seen = []

    class Number:
        def __init__(self, value): self.value = value
        def longLongValue(self): return self.value

    class Values:
        def objectForKey_(self, key):
            return {important_key: Number(17_435_592_029), total_key: Number(127_308_177_408)}.get(key)

    class Url:
        def resourceValuesForKeys_error_(self, keys, error):
            seen.append(keys)
            assert error is None
            return Values()

    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(
        ns=lambda value: value, nsurl=lambda path: Url()))
    assert collector._ios_volume_capacity() == {'free': 17_435_592_029, 'total': 127_308_177_408}
    assert seen == [[important_key, total_key]]


def test_ios_volume_unavailable_and_invalid_values_are_isolated(monkeypatch):
    from client.monitor import ios_dashboard as collector

    class InvalidNumber:
        def longLongValue(self): raise ValueError('unavailable')

    class Values:
        def objectForKey_(self, key):
            return InvalidNumber() if 'ImportantUsage' in key else types.SimpleNamespace(longLongValue=lambda: 127_308_177_408)

    class Url:
        def resourceValuesForKeys_error_(self, keys, error): return Values()

    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(
        ns=lambda value: value, nsurl=lambda path: Url()))
    assert collector._ios_volume_capacity() == {'free': None, 'total': 127_308_177_408}

    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(
        ns=lambda value: value, nsurl=lambda path: types.SimpleNamespace(resourceValuesForKeys_error_=lambda *args: None)))
    assert collector._ios_volume_capacity() == {'free': None, 'total': None}
