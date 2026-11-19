"""Common system information command, with platform-local collectors."""

import os
import shlex
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from client.commands.runtime.interrupts import timeout
from client.runtime.client_util import get_executable_path
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.commands.shell.decorators import shell_command
from core.device.local_identity import get_local_identity
from core.utils.command_output import StructuredCommandResult
from core.utils.formatting import format_bytes, seconds_to_readable_text, timestamp_to_readable_time


CORE_FIELDS = (
    'os_name', 'os_version', 'os_build', 'arch', 'manufacturer', 'model',
    'cpu_model', 'cpu_count', 'mem_total', 'mem_avail', 'pid', 'ppid',
    'process_name', 'username', 'hostname', 'launch_command', 'python_version',
    'system_boot_time', 'system_uptime', 'process_start_time', 'process_uptime',
)


def _optional(call):
    """An unavailable diagnostic field must not suppress other system information."""
    try:
        return call()
    except (CommandCancelledError, CommandTimeoutError):
        raise
    except Exception:
        return None


def _text(value):
    return value if value not in (None, '') else None


def _size(value):
    return format_bytes(value, trim_trailing_zeros=False) if value is not None else None


def _duration(value):
    return seconds_to_readable_text(max(0, value), compact=True) if value is not None else None


def _read(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace').strip()
    except (OSError, ValueError):
        return ''


def _process_launch_command(process):
    """Use the OS process command line, including runtime arguments."""
    args = process.cmdline()
    if not args:
        return None
    return subprocess.list2cmdline(args) if os.name == 'nt' else shlex.join(args)


def _default_shell():
    import pwd
    return _text(pwd.getpwuid(os.getuid()).pw_shell)


def collect_mac(owner):
    def command_text(command):
        result = owner.process_execution_service.run_shell_command(command, timeout=10)
        return _text(result.stdout.strip()) if result.returncode == 0 else None

    return {
        'os_build': _optional(lambda: command_text('sw_vers -buildVersion')),
        'cpu_model': _optional(lambda: command_text('sysctl -n machdep.cpu.brand_string')),
        'default_shell': _optional(_default_shell),
        'kernel': _text(platform.release()),
    }


def collect_windows(owner):
    from client.commands.platform.utils import win_util

    version = platform.version()
    sid = _optional(win_util.get_windows_uid_gid_sid) or {}
    return {
        'os_build': version.rsplit('.', 1)[-1] if version and version.rsplit('.', 1)[-1].isdigit() else None,
        'cpu_model': _text(platform.processor()),
        'locale': _optional(win_util.get_locale_tag),
        'user_sid': _text(sid.get('uid')),
        'group_sid': _text(sid.get('gid')),
        'integrity': _optional(win_util.get_integrity_level),
    }


def collect_linux(owner):
    release = {}
    for line in _read('/etc/os-release').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            release[key.strip()] = value.strip().strip('"')

    cpu_model = None
    for line in _read('/proc/cpuinfo').splitlines():
        if line.startswith('model name') and ':' in line:
            cpu_model = _text(line.split(':', 1)[1].strip())
            break

    return {
        'cpu_model': cpu_model,
        'default_shell': _optional(_default_shell),
        'kernel': _text(platform.release()),
        'distro_pretty_name': _text(release.get('PRETTY_NAME')),
        'package_manager': next((name for name in (
            'apt', 'dnf', 'yum', 'pacman', 'zypper', 'apk', 'emerge', 'xbps-install'
        ) if shutil.which(name)), None),
        'has_desktop': bool(any(os.environ.get(key) for key in (
            'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_CURRENT_DESKTOP', 'DESKTOP_SESSION'
        ))),
    }


def _ios_os_build(version_string):
    """Prefer the verified kernel build key, then the already-read NSProcessInfo string."""
    import ctypes
    import re

    try:
        lib = ctypes.CDLL(None, use_errno=True)
        sysctl = lib.sysctlbyname
        sysctl.argtypes = [ctypes.c_char_p, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
        sysctl.restype = ctypes.c_int
        size = ctypes.c_size_t()
        if sysctl(b'kern.osversion', None, ctypes.byref(size), None, 0) != 0:
            raise OSError(ctypes.get_errno(), 'kern.osversion size query failed')
        if not 1 <= size.value <= 256:
            raise ValueError('Invalid kern.osversion length')
        buffer = ctypes.create_string_buffer(size.value)
        if sysctl(b'kern.osversion', buffer, ctypes.byref(size), None, 0) != 0:
            raise OSError(ctypes.get_errno(), 'kern.osversion read failed')
        result = _text(buffer.raw[:size.value].rstrip(b'\x00').decode('utf-8', 'replace'))
        if result:
            return result
    except Exception:
        pass
    match = re.search(r'\bBuild\s+([A-Za-z0-9]+)\b', version_string or '', re.IGNORECASE)
    return match.group(1) if match else None


def _ios_process_start():
    """Get the Pythonista host process creation time via Darwin libproc."""
    import ctypes

    class ProcBSDInfo(ctypes.Structure):
        # XNU proc_bsdinfo, PROC_PIDTBSDINFO (3); this layout was device-probed.
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
    proc_pidinfo = lib.proc_pidinfo
    proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                             ctypes.c_void_p, ctypes.c_int]
    proc_pidinfo.restype = ctypes.c_int
    pid = os.getpid()
    info = ProcBSDInfo()
    received = proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if received != ctypes.sizeof(info) or info.pbi_pid != pid:
        raise OSError('Unable to read current process creation time')
    started = info.pbi_start_tvsec + info.pbi_start_tvusec / 1_000_000.0
    if not 1_577_836_800 <= started <= time.time() + 60:
        raise ValueError('Invalid process creation time')
    return started


def collect_ios(owner):
    from client.commands.platform.utils.ios_util import (
        get_ios_process_info, get_ios_device_info, get_ios_bundle_info,
        get_icloud_path, read_info_plist,
    )

    device = get_ios_device_info()
    process = get_ios_process_info()
    bundle = get_ios_bundle_info()
    # The same NSProcessInfo call also supplies handshake process identity.
    started = _optional(_ios_process_start)
    uptime = process.get('system_uptime_seconds')
    memory = process.get('physical_memory_bytes')
    from client.monitor.ios_dashboard import _system_memory
    vm = _optional(_system_memory)
    available = None
    if memory is not None and memory > 0 and vm is not None:
        if all(vm.get(key, -1) >= 0 for key in ('free', 'inactive')):
            available = min(memory, vm['free'] + vm['inactive'])
    return {
        'cpu_count': process.get('processor_count'),
        'mem_total': _size(memory),
        'mem_avail': _size(available),
        'username': _text(process.get('username')),
        'process_name': _text(process.get('process_name')),
        'system_boot_time': timestamp_to_readable_time(time.time() - uptime) if uptime is not None else None,
        'system_uptime': _duration(uptime),
        'process_start_time': timestamp_to_readable_time(started) if started is not None else None,
        'process_uptime': _duration(time.time() - started) if started is not None else None,
        'os_build': _ios_os_build(process.get('operating_system_version_string')),
        'cpu_model': None,
        'kernel': _text(platform.release()),
        'device_name': device.get('device_name'),
        'device_model': device.get('device_model'),
        'device_type': device.get('device_type'),
        'machine_name': device.get('machine_name'),
        'identifier_for_vendor': device.get('identifier_for_vendor'),
        'bundle_identifier': bundle.get('bundle_identifier'),
        'bundle_path': bundle.get('bundle_path'),
        'bundle_executable_path': bundle.get('executable_path') or sys.executable,
        'bundle_name': bundle.get('bundle_name'),
        'app_name': bundle.get('app_name'),
        'bundle_version': bundle.get('bundle_version'),
        'bundle_short_version': bundle.get('bundle_short_version'),
        'low_power_mode_enabled': process.get('low_power_mode_enabled'),
        'home': os.path.expanduser('~'),
        'documents': os.path.expanduser('~/Documents'),
        'temp': os.path.abspath(os.getenv('TMPDIR', '/tmp')),
        'icloud': _optional(lambda: get_icloud_path(read_info_plist())),
    }


COLLECTORS = {
    'mac': collect_mac,
    'win': collect_windows,
    'linux': collect_linux,
    'ios': collect_ios,
}


@shell_command('Get system information', group='system')
@timeout(30)
def getinfo(self, arg=''):
    """Return ordered local identity, fresh process metrics and platform fields."""
    if str(arg or '').strip() not in ('', 'json', '--json'):
        return 0, 'Usage: getinfo [--json]'
    try:
        identity = get_local_identity()
        self._checkpoint()
        now = time.time()
        data = dict.fromkeys(CORE_FIELDS)
        data.update({
            'os_name': _text(identity.os_name),
            'os_version': _text(identity.os_version),
            'arch': _text(identity.arch),
            'manufacturer': _text(identity.manufacturer),
            'model': _text(identity.model),
            'cpu_count': _optional(os.cpu_count),
            'pid': os.getpid(),
            'ppid': _optional(os.getppid),
            'hostname': _text(identity.hostname),
            'launch_command': _optional(get_executable_path),
            'python_version': platform.python_version(),
        })
        if identity.os_alias != 'ios':
            import psutil
            memory = _optional(psutil.virtual_memory)
            process = _optional(psutil.Process)
            data['username'] = _optional(process.username) if process is not None else None
            data['process_name'] = _optional(process.name) if process is not None else None
            if process is not None:
                data['launch_command'] = _optional(lambda: _process_launch_command(process)) or data['launch_command']
            data['mem_total'] = _size(memory.total) if memory is not None else None
            data['mem_avail'] = _size(memory.available) if memory is not None else None
            boot = _optional(psutil.boot_time)
            start = _optional(process.create_time) if process is not None else None
            data['system_boot_time'] = timestamp_to_readable_time(boot) if boot is not None else None
            data['system_uptime'] = _duration(now - boot) if boot is not None else None
            data['process_start_time'] = timestamp_to_readable_time(start) if start is not None else None
            data['process_uptime'] = _duration(now - start) if start is not None else None
        collector = COLLECTORS[identity.os_alias]
        data.update(collector(self))
        # The common fields precede platform-specific diagnostics.
        return StructuredCommandResult(status=1, data=data, shape='dict', width=24, null_text='N/A')
    except (CommandCancelledError, CommandTimeoutError):
        raise
    except Exception as exc:
        return 0, f'Failed to collect system information: {exc}'

