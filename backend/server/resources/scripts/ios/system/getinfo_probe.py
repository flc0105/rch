SCRIPT_METADATA = {
    'name': 'ios/system/getinfo_probe',
    'display_name': 'iOS Getinfo Probe',
    'description': 'Probe iOS build, process start time, CPU identifiers and Dashboard memory.',
    'category': 'System',
    'platforms': ['ios'],
    'execution': {
        'modes': {'allowed': ['inproc'], 'default': 'inproc'},
        'output': {'allowed': ['collect', 'stream'], 'default': 'stream'},
    },
    'params': [],
}

import ctypes
import datetime
import json
import os
import re
import time

from core.utils.formatting import format_bytes


def _read_sysctl(name):
    """Try a read-only Darwin sysctl key. Some keys are sandbox-restricted."""
    lib = ctypes.CDLL(None, use_errno=True)
    func = lib.sysctlbyname
    func.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                     ctypes.c_void_p, ctypes.c_size_t]
    func.restype = ctypes.c_int
    key = name.encode('ascii')
    size = ctypes.c_size_t()
    if func(key, None, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), name)
    if size.value < 1 or size.value > 4096:
        raise ValueError('Unexpected sysctl result length: {}'.format(size.value))
    raw = ctypes.create_string_buffer(size.value)
    if func(key, raw, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), name)
    if name in ('hw.cputype', 'hw.cpusubtype', 'hw.cpufamily'):
        if size.value != 4:
            raise ValueError('Expected 4-byte integer; got {} bytes'.format(size.value))
        return int.from_bytes(raw.raw[:4], 'little')
    return raw.raw[:size.value].rstrip(b'\x00').decode('utf-8', 'replace')


def _read_process_start():
    """Read this *host process* creation time via libproc (Darwin proc_bsdinfo)."""
    class ProcBSDInfo(ctypes.Structure):
        # Apple XNU sys/proc_info.h, PROC_PIDTBSDINFO (3), MAXCOMLEN=16.
        _fields_ = [
            ('pbi_flags', ctypes.c_uint32), ('pbi_status', ctypes.c_uint32),
            ('pbi_xstatus', ctypes.c_uint32), ('pbi_pid', ctypes.c_uint32),
            ('pbi_ppid', ctypes.c_uint32), ('pbi_uid', ctypes.c_uint32),
            ('pbi_gid', ctypes.c_uint32), ('pbi_ruid', ctypes.c_uint32),
            ('pbi_rgid', ctypes.c_uint32), ('pbi_svuid', ctypes.c_uint32),
            ('pbi_svgid', ctypes.c_uint32), ('rfu_1', ctypes.c_uint32),
            ('pbi_comm', ctypes.c_char * 16), ('pbi_name', ctypes.c_char * 32),
            ('pbi_nfiles', ctypes.c_uint32), ('pbi_pgid', ctypes.c_uint32),
            ('pbi_pjobc', ctypes.c_uint32), ('e_tdev', ctypes.c_uint32),
            ('e_tpgid', ctypes.c_uint32), ('pbi_nice', ctypes.c_int32),
            ('pbi_start_tvsec', ctypes.c_uint64), ('pbi_start_tvusec', ctypes.c_uint64),
        ]

    try:
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    except OSError:
        lib = ctypes.CDLL(None, use_errno=True)
    func = lib.proc_pidinfo
    func.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    func.restype = ctypes.c_int
    info = ProcBSDInfo()
    pid = os.getpid()
    received = func(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if received != ctypes.sizeof(info):
        code = ctypes.get_errno()
        raise OSError('proc_pidinfo returned {} of {} bytes (errno={} {})'.format(
            received, ctypes.sizeof(info), code, os.strerror(code) if code else ''))
    if info.pbi_pid != pid:
        raise ValueError('PID mismatch: expected {}, received {}'.format(pid, info.pbi_pid))
    started = info.pbi_start_tvsec + info.pbi_start_tvusec / 1_000_000.0
    now = time.time()
    if not 1_577_836_800 <= started <= now + 60:
        raise ValueError('Implausible process start timestamp: {}'.format(started))
    return {
        'pid': pid,
        'process_start_time': datetime.datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M:%S'),
        'process_start_epoch': round(started, 6),
        'process_uptime_seconds': round(max(now - started, 0), 1),
    }


def _read_dashboard_memory():
    # Reuse the verified iOS Dashboard VM collector: do not duplicate Mach structs.
    from client.monitor.ios_dashboard import _system_memory
    from objc_util import ObjCClass

    total = int(ObjCClass('NSProcessInfo').processInfo().physicalMemory())
    vm = _system_memory()
    available = min(total, vm['free'] + vm['inactive'])
    if total <= 0 or any(value < 0 for value in vm.values()):
        raise ValueError('Invalid physical memory or VM counters')
    return {
        'mem_total': format_bytes(total, trim_trailing_zeros=False),
        'mem_avail': format_bytes(available, trim_trailing_zeros=False),
        'mem_total_bytes': total,
        'mem_avail_bytes': available,
        'dashboard_free_bytes': vm['free'],
        'dashboard_inactive_bytes': vm['inactive'],
        'dashboard_active_bytes': vm['active'],
        'dashboard_wired_bytes': vm['wired'],
    }


def _read_version():
    from objc_util import ObjCClass

    version_string = str(ObjCClass('NSProcessInfo').processInfo().operatingSystemVersionString())
    match = re.search(r'\bBuild\s+([A-Za-z0-9]+)\b', version_string, re.IGNORECASE)
    return {
        'os_version_string': version_string,
        'os_build_from_version_string': match.group(1) if match else None,
    }


def _probe(label, fn, report):
    try:
        value = fn()
        report[label] = {'ok': True, 'value': value}
        print('[OK] {}'.format(label), flush=True)
    except Exception as exc:
        report[label] = {'ok': False, 'error': '{}: {}'.format(type(exc).__name__, exc)}
        print('[UNAVAILABLE] {}: {}: {}'.format(label, type(exc).__name__, exc), flush=True)


def main():
    print('iOS getinfo probe — read-only; host PID {}'.format(os.getpid()), flush=True)
    report = {}
    _probe('os_version_string', _read_version, report)
    _probe('kern.osversion', lambda: _read_sysctl('kern.osversion'), report)
    _probe('process_start_libproc', _read_process_start, report)
    _probe('dashboard_memory', _read_dashboard_memory, report)
    for key in ('machdep.cpu.brand_string', 'hw.model', 'hw.machine', 'hw.cpufamily'):
        _probe(key, lambda name=key: _read_sysctl(name), report)
    print('\n=== COPY THE FULL JSON RESULT ===', flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print('=== END iOS GETINFO PROBE ===', flush=True)


main()
