"""Common system information command, with platform-local collectors."""

import json
import os
import re
from functools import lru_cache
import platform
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from client.commands.runtime.interrupts import timeout
from client.runtime.client_util import get_executable_path
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from client.commands.shell.decorators import shell_command
from core.device.apple_models import resolve_apple_model_name
from core.device.local_identity import get_local_identity
from core.utils.command_output import StructuredCommandResult
from core.utils.formatting import format_bytes, seconds_to_readable_text, timestamp_to_readable_time


CORE_FIELDS = (
    'os_name', 'os_product', 'os_version', 'os_build', 'arch', 'manufacturer', 'model',
    'cpu_model', 'cpu_count', 'gpu_models', 'mem_total', 'mem_avail', 'pid', 'ppid',
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



def _base_os_product(identity):
    version = _text(identity.os_version)
    if identity.os_alias == 'mac':
        return f'macOS {version}' if version else 'macOS'
    if identity.os_alias == 'ios':
        return f'iOS {version}' if version else 'iOS'
    return None


@lru_cache(maxsize=1)
def _read_windows_os_caption():
    """Read the local Windows product caption from WMI; cache across getinfo calls."""
    command = (
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        '(Get-CimInstance -ClassName Win32_OperatingSystem).Caption'
    )
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            check=False,
        )
        return _text(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _read_windows_current_version():
    """Read native Windows release metadata from the CurrentVersion registry key."""
    try:
        import winreg

        path = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        access = getattr(winreg, 'KEY_READ', 0) | getattr(winreg, 'KEY_WOW64_64KEY', 0)
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access)
        try:
            values = {}
            for name in (
                'ProductName', 'DisplayVersion', 'CurrentBuildNumber',
                'InstallationType', 'EditionID',
            ):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    continue
            return values
        finally:
            winreg.CloseKey(key)
    except (ImportError, OSError, AttributeError):
        return {}


def _windows_build_number(registry):
    value = str(_text(registry.get('CurrentBuildNumber')) or '').strip()
    if value.isdigit():
        return value
    version = platform.version()
    candidate = version.rsplit('.', 1)[-1] if version else ''
    return candidate if candidate.isdigit() else None


def _windows_os_product(registry, caption):
    """Use the Windows-supplied product name; append client release metadata."""
    caption = str(_text(caption) or '').strip()
    if caption.casefold().startswith('microsoft '):
        caption = caption[len('Microsoft '):].strip()
    product_name = str(_text(registry.get('ProductName')) or '').strip()
    if product_name.casefold().startswith('microsoft '):
        product_name = product_name[len('Microsoft '):].strip()
    installation_type = str(registry.get('InstallationType') or '').casefold()
    is_server = installation_type.startswith('server') or 'windows server' in caption.casefold()
    if is_server:
        if 'windows server' in caption.casefold():
            return caption
        if 'windows server' in product_name.casefold():
            return product_name
        return 'Windows Server'

    # A Windows 11 registry may retain an older Windows 10 ProductName.
    if not caption or 'windows' not in caption.casefold():
        caption = product_name if 'windows' in product_name.casefold() else ''
        if 'windows 10' in caption.casefold():
            # Without a working system Caption this registry value is not reliable.
            caption = 'Windows'
        if not caption:
            caption = 'Windows'
    display_version = _text(registry.get('DisplayVersion'))
    return f'{caption} {display_version}' if display_version else caption


@lru_cache(maxsize=1)
def _read_windows_hardware():
    """Read CPU names and enabled PCI graphics adapters from native Windows CIM."""
    command = (
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        '$cpu = @(Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | '
        'ForEach-Object { $_.Name }); '
        '$gpu = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | '
        r"Where-Object { $_.PNPDeviceID -match '^PCI\\VEN_' -and "
        '$_.ConfigManagerErrorCode -eq 0 } | '
        'ForEach-Object { $_.Name }); '
        '[pscustomobject]@{cpu_models=$cpu; gpu_models=$gpu} | '
        'ConvertTo-Json -Compress -Depth 3'
    )
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        check=False,
    )
    if result.returncode:
        return {}
    data = json.loads(result.stdout)
    return data if isinstance(data, dict) else {}


def _name_list(values):
    """Keep a stable list of nonempty distinct adapter names."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return None
    names = list(dict.fromkeys(
        name for value in values if (name := str(value or '').strip())
    ))
    return names or None


def _windows_processor_name_from_registry():
    """Fallback to the local processor marketing name when CIM is unavailable."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
        return _text(str(winreg.QueryValueEx(key, 'ProcessorNameString')[0]).strip())


def _mac_gpu_models(owner):
    result = owner.process_execution_service.run_shell_command(
        'system_profiler SPDisplaysDataType -json', timeout=8)
    if result.returncode:
        return None
    records = json.loads(result.stdout).get('SPDisplaysDataType') or []
    if not isinstance(records, list):
        return None
    return _name_list([
        record.get('spdisplays_chipset-model') or record.get('sppci_model')
        for record in records if isinstance(record, dict)
    ])


def _linux_gpu_models():
    if not shutil.which('lspci'):
        return None
    result = subprocess.run(
        ['lspci', '-nn'], capture_output=True, text=True, timeout=5,
        encoding='utf-8', errors='replace', check=False)
    if result.returncode:
        return None
    names = []
    for line in result.stdout.splitlines():
        match = re.search(
            r'\b(?:VGA compatible controller|3D controller|Display controller)'
            r'(?: \[[0-9a-fA-F]{4}\])?:\s*(.*)', line, re.IGNORECASE)
        if match:
            # Remove trailing vendor:device PCI identifier while retaining model names.
            name = re.sub(r'\s+\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\](?=\s|$)',
                          '', match.group(1)).strip()
            if name:
                names.append(name)
    return _name_list(names)


def collect_mac(owner):
    def command_text(command):
        result = owner.process_execution_service.run_shell_command(command, timeout=10)
        return _text(result.stdout.strip()) if result.returncode == 0 else None

    return {
        'os_build': _optional(lambda: command_text('sw_vers -buildVersion')),
        'cpu_model': _optional(lambda: command_text('sysctl -n machdep.cpu.brand_string')),
        'gpu_models': _optional(lambda: _mac_gpu_models(owner)),
        'default_shell': _optional(_default_shell),
        'kernel': _text(platform.release()),
    }


def collect_windows(owner):
    from client.commands.platform.utils import win_util

    registry = _optional(_read_windows_current_version) or {}
    build = _windows_build_number(registry)
    sid = _optional(win_util.get_windows_uid_gid_sid) or {}
    hardware = _optional(_read_windows_hardware) or {}
    processors = _name_list(hardware.get('cpu_models')) or []
    return {
        'os_product': _windows_os_product(registry, _read_windows_os_caption()),
        'os_build': build,
        'cpu_model': (processors[0] if processors else
                      _optional(_windows_processor_name_from_registry)),
        'gpu_models': _name_list(hardware.get('gpu_models')),
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

    product = _text(release.get('PRETTY_NAME'))
    if product is None:
        name = _text(release.get('NAME'))
        version = _text(release.get('VERSION')) or _text(release.get('VERSION_ID'))
        product = f'{name} {version}'.strip() if name and version else name or version

    return {
        'os_product': product,
        'os_build': _text(release.get('BUILD_ID')),
        'cpu_model': cpu_model,
        'gpu_models': _optional(_linux_gpu_models),
        'default_shell': _optional(_default_shell),
        'kernel': _text(platform.release()),
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
    result = {
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
    machine_name = str(device.get('machine_name') or '')
    if (device.get('device_type') == 'Pad' or machine_name.startswith('iPad')):
        version = _text(device.get('system_version'))
        if version:
            result['os_product'] = f'iPadOS {version}'
    return result


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
            'os_product': _base_os_product(identity),
            'os_version': _text(identity.os_version),
            'arch': _text(identity.arch),
            'manufacturer': _text(identity.manufacturer),
            'model': (resolve_apple_model_name(identity.model)
                      if identity.os_alias in ('mac', 'ios') else _text(identity.model)),
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

