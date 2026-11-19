"""Platform-local collectors for the getinfo Standalone command.

Each collector accepts `detailed=False` and skips expensive diagnostic probes
until --all/-a is requested. These functions return ordinary field values.
"""

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError
from core.device.apple_models import resolve_apple_chip_name
from core.utils.formatting import format_bytes, seconds_to_readable_text, timestamp_to_readable_time


def _optional(call):
    """Ignore unavailable diagnostic fields, preserving command cancellation."""
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



def _default_shell():
    import pwd
    return _text(pwd.getpwuid(os.getuid()).pw_shell)



def _default_shell_version(shell):
    """Version of the account's configured login shell, not the current PTY shell."""
    if not shell:
        return None
    result = subprocess.run(
        [shell, '--version'], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=2, check=False,
    )
    if result.returncode:
        return None
    line = (result.stdout or result.stderr).strip().splitlines()
    return _text(line[0].strip()) if line else None



def _name_list(values):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return None
    names = list(dict.fromkeys(
        name for value in values if (name := str(value or '').strip())
    ))
    return names or None



def _read_windows_current_version():
    try:
        import winreg
        path = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        access = getattr(winreg, 'KEY_READ', 0) | getattr(winreg, 'KEY_WOW64_64KEY', 0)
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access)
        try:
            result = {}
            for name in ('ProductName', 'DisplayVersion', 'CurrentBuildNumber',
                         'InstallationType', 'EditionID', 'UBR'):
                try:
                    result[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
            return result
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



def _windows_nt_version(registry):
    ver = _optional(sys.getwindowsversion)
    if ver is not None:
        version = f'{ver.major}.{ver.minor}.{ver.build}'
    else:
        version = platform.version()
    ubr = registry.get('UBR')
    if isinstance(ubr, int) and ubr >= 0 and version.count('.') == 2:
        version += f'.{ubr}'
    return f'Windows NT {version}' if version else 'Windows NT'



@lru_cache(maxsize=1)
def _windows_brand():
    """Native Windows product title. The returned winbrand buffer is caller-owned."""
    library = ctypes.WinDLL('winbrand.dll', use_last_error=True)
    branding = library.BrandingFormatString
    branding.argtypes = [ctypes.c_wchar_p]
    branding.restype = ctypes.c_void_p
    pointer = branding('%WINDOWS_LONG%')
    if not pointer:
        return None
    try:
        return _text(ctypes.wstring_at(pointer).strip())
    finally:
        kernel = ctypes.WinDLL('kernel32.dll', use_last_error=True)
        kernel.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel.GlobalFree.restype = ctypes.c_void_p
        kernel.GlobalFree(pointer)



def _windows_os_product(registry, brand):
    brand = str(_text(brand) or '').removeprefix('Microsoft ').strip()
    if not brand or 'windows' not in brand.casefold():
        brand = str(_text(registry.get('ProductName')) or '').removeprefix('Microsoft ').strip()
        if 'windows 10' in brand.casefold():
            # Some Windows 11 installations retain the old registry ProductName.
            brand = 'Windows'
        if not brand:
            brand = 'Windows'
    version = _text(registry.get('DisplayVersion'))
    return f'{brand} {version}' if version else brand



def _windows_processor_name_from_registry():
    """Equivalent to HKLM:\\HARDWARE\\...\\CentralProcessor\\0 ProcessorNameString."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
        return _text(str(winreg.QueryValueEx(key, 'ProcessorNameString')[0]).strip())



@lru_cache(maxsize=1)
def _read_windows_hardware():
    """Full mode only: enabled physical PCI GPUs; CPU never uses CIM/WMI."""
    command = (
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        '$gpu = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | '
        r"Where-Object { $_.PNPDeviceID -match '^PCI\\VEN_' -and "
        '$_.ConfigManagerErrorCode -eq 0 } | ForEach-Object { $_.Name }); '
        '@{gpu_models=$gpu} | ConvertTo-Json -Compress -Depth 3'
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
            name = re.sub(r'\s+\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\](?=\s|$)',
                          '', match.group(1)).strip()
            if name:
                names.append(name)
    return _name_list(names)



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



def collect_mac(owner, *, detailed=False):
    """Mac account and CPU data are cheap; build and GPU need external tools."""
    def command_text(command):
        result = owner.process_execution_service.run_shell_command(command, timeout=10)
        return _text(result.stdout.strip()) if result.returncode == 0 else None

    shell = _optional(_default_shell)
    result = {
        'cpu_model': _optional(lambda: command_text('sysctl -n machdep.cpu.brand_string')),
        'default_shell': shell,
        'default_shell_version': _optional(lambda: _default_shell_version(shell)),
    }
    if detailed:
        result.update({
            'os_build': _optional(lambda: command_text('sw_vers -buildVersion')),
            'gpu_models': _optional(lambda: _mac_gpu_models(owner)),
        })
    return result



def collect_windows(owner, *, detailed=False):
    """Native registry/token fields first; PowerShell GPU query only for --all."""
    from client.commands.platform.utils import win_util

    registry = _optional(_read_windows_current_version) or {}
    result = {
        'cpu_model': _optional(_windows_processor_name_from_registry),
        'kernel': _windows_nt_version(registry),
        'integrity': _optional(win_util.get_integrity_level),
    }
    if detailed:
        sid = _optional(win_util.get_windows_uid_gid_sid) or {}
        hardware = _optional(_read_windows_hardware) or {}
        result.update({
            'os_product': _windows_os_product(registry, _optional(_windows_brand)),
            'os_build': _windows_build_number(registry),
            'gpu_models': _name_list(hardware.get('gpu_models')),
            'locale': _optional(win_util.get_locale_tag),
            'user_sid': _text(sid.get('uid')),
            'group_sid': _text(sid.get('gid')),
        })
    return result



def _linux_release():
    release = {}
    for line in _read('/etc/os-release').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            release[key.strip()] = value.strip().strip('"')
    return release



def _linux_cpu_model():
    for line in _read('/proc/cpuinfo').splitlines():
        if line.startswith('model name') and ':' in line:
            return _text(line.split(':', 1)[1].strip())
    return None



def collect_linux(owner, *, detailed=False):
    shell = _optional(_default_shell)
    result = {
        'cpu_model': _linux_cpu_model(),
        'default_shell': shell,
        'default_shell_version': _optional(lambda: _default_shell_version(shell)),
    }
    if detailed:
        release = _linux_release()
        product = _text(release.get('PRETTY_NAME'))
        if not product:
            name = _text(release.get('NAME'))
            version = _text(release.get('VERSION')) or _text(release.get('VERSION_ID'))
            product = f'{name} {version}'.strip() if name and version else name or version
        result.update({
            'os_product': product,
            'os_build': _text(release.get('BUILD_ID')),
            'gpu_models': _optional(_linux_gpu_models),
        })
    return result



def collect_ios(owner, *, detailed=False):
    from client.commands.platform.utils.ios_util import (
        get_ios_process_info, get_ios_device_info, get_ios_bundle_info,
        get_icloud_path, read_info_plist,
    )
    from client.monitor.ios_dashboard import _system_memory

    device = get_ios_device_info()
    process = get_ios_process_info()
    bundle = get_ios_bundle_info()
    started = _optional(_ios_process_start)
    uptime = process.get('system_uptime_seconds')
    memory = process.get('physical_memory_bytes')
    vm = _optional(_system_memory)
    available = None
    if memory is not None and memory > 0 and vm is not None:
        if all(vm.get(key, -1) >= 0 for key in ('free', 'inactive')):
            available = min(memory, vm['free'] + vm['inactive'])

    result = {
        'cpu_model': resolve_apple_chip_name(device.get('machine_name')),
        'cpu_count': process.get('processor_count'),
        'mem_total': _size(memory),
        'mem_avail': _size(available),
        'username': _text(process.get('username')),
        'process_name': _text(process.get('process_name')),
        'system_uptime': _duration(uptime),
        'process_uptime': _duration(time.time() - started) if started is not None else None,
        'device_name': device.get('device_name'),
        'device_model': device.get('device_model'),
        'device_type': device.get('device_type'),
        'app_name': bundle.get('app_name'),
        'bundle_identifier': bundle.get('bundle_identifier'),
    }
    if detailed:
        result.update({
            'os_build': _ios_os_build(process.get('operating_system_version_string')),
            'system_boot_time': timestamp_to_readable_time(time.time() - uptime) if uptime is not None else None,
            'process_start_time': timestamp_to_readable_time(started) if started is not None else None,
            'machine_name': device.get('machine_name'),
            'identifier_for_vendor': device.get('identifier_for_vendor'),
            'bundle_path': bundle.get('bundle_path'),
            'bundle_executable_path': bundle.get('executable_path') or sys.executable,
            'bundle_name': bundle.get('bundle_name'),
            'bundle_version': bundle.get('bundle_version'),
            'bundle_short_version': bundle.get('bundle_short_version'),
            'low_power_mode_enabled': process.get('low_power_mode_enabled'),
            'home': os.path.expanduser('~'),
            'documents': os.path.expanduser('~/Documents'),
            'temp': os.path.abspath(os.getenv('TMPDIR', '/tmp')),
            'icloud': _optional(lambda: get_icloud_path(read_info_plist())),
        })
        machine_name = str(device.get('machine_name') or '')
        if device.get('device_type') == 'Pad' or machine_name.startswith('iPad'):
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
