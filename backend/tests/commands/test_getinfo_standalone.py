"""Four-platform getinfo contract and collection boundaries."""
import json
from types import SimpleNamespace

import pytest

from client.commands.runtime.hosts import MacCommands, WindowsCommands, LinuxCommands, iOSCommands
from client.commands.shell.standalone import getinfo as info
from core.utils.command_output import StructuredCommandResult, render_structured_result
from core.utils.formatting import seconds_to_readable_text


@pytest.mark.parametrize('cls', [MacCommands, WindowsCommands, LinuxCommands, iOSCommands])
def test_one_common_getinfo_mount(cls):
    handler = cls(None).getinfo
    assert handler.__func__ is info.getinfo
    assert handler.__module__ == info.__name__
    assert handler.group == 'system'


def test_compact_duration_drops_only_leading_zeros():
    assert seconds_to_readable_text(0, compact=True) == '0s'
    assert seconds_to_readable_text(50, compact=True) == '50s'
    assert seconds_to_readable_text(125, compact=True) == '2m 5s'
    assert seconds_to_readable_text(3605, compact=True) == '1h 0m 5s'
    assert seconds_to_readable_text(34 * 86400 + 2 * 3600 + 6 * 60 + 50, compact=True) == '34d 2h 6m 50s'
    assert seconds_to_readable_text(50) == '0d 0h 0m 50s'


@pytest.mark.parametrize('platform', ['mac', 'win', 'linux', 'ios'])
def test_order_and_exact_common_field_types(monkeypatch, platform):
    identity = SimpleNamespace(os_alias=platform, os_name='Test OS', os_version='1.0',
                               arch='amd64', manufacturer='Maker', model='Box', hostname='unit')
    monkeypatch.setattr(info, 'get_local_identity', lambda: identity)
    if platform == 'ios':
        monkeypatch.setitem(info.COLLECTORS, platform, lambda owner: {
            'cpu_count': 6, 'mem_total': '6.00 GB', 'username': 'ios-user',
            'system_uptime': '50s', 'kernel': 'Darwin', 'device_name': 'iPad',
        })
    else:
        monkeypatch.setitem(info.COLLECTORS, platform, lambda owner: {'kernel': 'Test Kernel'})
    monkeypatch.setattr(info, 'get_executable_path', lambda: 'python rchclient.py')
    monkeypatch.setattr(info, '_process_launch_command', lambda process: None)
    result = info.getinfo(SimpleNamespace(_checkpoint=lambda: None))
    assert isinstance(result, StructuredCommandResult)
    assert tuple(result.data)[:len(info.CORE_FIELDS)] == info.CORE_FIELDS
    assert info.CORE_FIELDS.index('process_name') == info.CORE_FIELDS.index('ppid') + 1
    assert result.data['os_name'] == 'Test OS'
    assert result.data['model'] == 'Box'
    assert result.data['os_product'] == {'mac': 'macOS 1.0', 'ios': 'iOS 1.0'}.get(platform)
    assert result.data['python_version'].count('.') >= 1
    assert result.data['launch_command'] == 'python rchclient.py'
    assert result.data['kernel'] == ('Darwin' if platform == 'ios' else 'Test Kernel')
    if platform != 'ios':
        assert isinstance(result.data['pid'], int)
        assert isinstance(result.data['mem_total'], str)
    else:
        assert result.data['mem_avail'] is None  # This mock only supplies selected iOS fields.
        assert result.data['process_start_time'] is None
        assert result.data['process_uptime'] is None
    status, json_result = render_structured_result(result, output_format='json')
    assert status == 1
    assert list(json.loads(json_result)) == list(result.data)
    if platform == 'ios':
        assert 'mem_avail' in render_structured_result(result)[1]
        assert 'N/A' in render_structured_result(result)[1]
    assert info.getinfo(SimpleNamespace(), '--not-an-option')[0] == 0


def test_ios_snapshot_reused_and_optional_icloud_failure(monkeypatch):
    from client.commands.platform.utils import ios_util
    calls = []
    from client.monitor import ios_dashboard
    monkeypatch.setattr(info, '_ios_process_start', lambda: 1_794_995_448.0)
    monkeypatch.setattr(info, '_ios_os_build', lambda version: '22B91' if 'Build 22B91' in version else None)
    monkeypatch.setattr(ios_dashboard, '_system_memory', lambda: {'free': 1_073_741_824, 'inactive': 2_147_483_648})
    monkeypatch.setattr(ios_util, 'get_ios_process_info', lambda: calls.append('process') or {
        'process_name': 'Pythonista', 'processor_count': 4,
        'physical_memory_bytes': 8589934592, 'system_uptime_seconds': 50,
        'username': 'ios-user', 'low_power_mode_enabled': True,
        'operating_system_version_string': 'Version 18.1.1 (Build 22B91)',
    })
    monkeypatch.setattr(ios_util, 'get_ios_device_info', lambda: {
        'device_name': 'iPhone', 'device_model': 'iPhone', 'device_type': 'Phone',
        'machine_name': 'iPhone16,2', 'identifier_for_vendor': 'device-id',
    })
    monkeypatch.setattr(ios_util, 'get_ios_bundle_info', lambda: {
        'bundle_identifier': 'app.test', 'executable_path': '/app/bin',
    })
    monkeypatch.setattr(ios_util, 'read_info_plist', lambda: (_ for _ in ()).throw(OSError('denied')))
    data = info.collect_ios(None)
    assert calls == ['process']
    assert data['mem_total'] == '8.00 GB'
    assert data['mem_avail'] == '3.00 GB'
    assert data['os_build'] == '22B91'
    assert data['process_start_time'] is not None
    assert data['process_uptime'] is not None
    assert data['system_uptime'] == '50s'
    assert data['system_boot_time'] is not None
    assert data['icloud'] is None
    assert data['process_name'] == 'Pythonista'
    assert data['device_name'] == 'iPhone'
    assert list(data).index('kernel') < list(data).index('device_name')
    assert data['bundle_identifier'] == 'app.test'
    assert not set(data) & {'platform', 'kernel_version', 'python_compiler', 'python_version_full',
                            'os_version_string', 'cwd', 'current_shell'}


def test_mac_collector_reuses_process_service_and_fails_soft(monkeypatch):
    calls = []
    def fake_shell(command, timeout):
        calls.append((command, timeout))
        if command.startswith('sysctl'):
            raise OSError('unavailable')
        return SimpleNamespace(returncode=0, stdout='24A123\n')
    owner = SimpleNamespace(process_execution_service=SimpleNamespace(run_shell_command=fake_shell))
    data = info.collect_mac(owner)
    assert data['os_build'] == '24A123'
    assert data['cpu_model'] is None
    assert ('sw_vers -buildVersion', 10) in calls


def test_linux_missing_optional_files_and_metrics(monkeypatch):
    monkeypatch.setattr(info, '_read', lambda path: '')
    fields = info.collect_linux(None)
    assert fields['cpu_model'] is None
    assert fields['os_product'] is None
    assert fields['os_build'] is None
    assert 'distro_pretty_name' not in fields
    assert fields['has_desktop'] in (False, True)
    assert 'package_manager' in fields and 'package_manger' not in fields
    assert not set(fields) & {'current_shell', 'python_executable', 'gpu', 'ip', 'resolution',
                               'is_root', 'cmdline', 'exe', 'cwd'}
    assert list(fields).index('os_product') < list(fields).index('package_manager') < list(fields).index('has_desktop')


def test_windows_sid_fields_and_build(monkeypatch):
    from client.commands.platform import utils as platform_utils
    fake_win_util = SimpleNamespace(
        get_windows_uid_gid_sid=lambda: {'uid': 'S-1-5-user', 'gid': 'S-1-5-group'},
        get_locale_tag=lambda: 'en-US',
        get_integrity_level=lambda: 'High',
    )
    monkeypatch.setattr(platform_utils, 'win_util', fake_win_util, raising=False)
    monkeypatch.setattr(info, '_read_windows_current_version', lambda: {
        'ProductName': 'Windows 10 Pro', 'DisplayVersion': '25H2',
        'CurrentBuildNumber': '26200', 'InstallationType': 'Client',
    })
    monkeypatch.setattr(info.platform, 'version', lambda: '10.0.26200')
    monkeypatch.setattr(info.platform, 'processor', lambda: 'AMD64 Family 25 Model 1')
    monkeypatch.setattr(info, '_read_windows_os_caption', lambda: 'Microsoft Windows 11 Pro')
    fields = info.collect_windows(None)
    assert fields['os_build'] == '26200'
    assert fields['os_product'] == 'Windows 11 Pro 25H2'
    assert fields['user_sid'] == 'S-1-5-user'
    assert fields['group_sid'] == 'S-1-5-group'
    assert fields['locale'] == 'en-US'
    assert fields['integrity'] == 'High'
    assert fields['cpu_model'] == 'AMD64 Family 25 Model 1'
    assert not any(field in fields for field in ('uid', 'gid', 'processor',
                                                  'python_version_full', 'reconnect_interval', 'cwd'))


def test_launch_command_includes_original_process_runtime_arguments():
    """Unlike reconstructed sys.argv, OS process argv retains consumed startup options."""
    import shlex
    process = SimpleNamespace(cmdline=lambda: [
        '/usr/bin/python3', '/opt/rch/client.py', '--update-ready-file', '/tmp/ready a.json',
    ])
    assert shlex.split(info._process_launch_command(process)) == process.cmdline()


def test_ios_os_build_reads_kernel_and_falls_back_to_nsprocessinfo(monkeypatch):
    import ctypes
    real_cdll = ctypes.CDLL
    raw = b'22B91\x00'

    class Sysctl:
        argtypes = None
        restype = None

        def __call__(self, key, out, size_ptr, oldp, newlen):
            assert key == b'kern.osversion'
            size = ctypes.cast(size_ptr, ctypes.POINTER(ctypes.c_size_t))
            if out is None:
                size[0] = len(raw)
            else:
                ctypes.memmove(out, raw, len(raw))
            return 0

    class Library:
        sysctlbyname = Sysctl()

    monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: Library())
    assert info._ios_os_build('Version 18.1.1 (Build INVALID)') == '22B91'
    monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('denied')))
    assert info._ios_os_build('Version 18.1.1 (Build 22B91)') == '22B91'
    assert info._ios_os_build('Version unknown') is None
    monkeypatch.setattr(ctypes, 'CDLL', real_cdll)


def test_ios_process_start_native_layout(monkeypatch):
    import ctypes
    real_cdll = ctypes.CDLL
    start = 1_794_995_448
    pid = info.os.getpid()

    class ProcInfo:
        argtypes = None
        restype = None

        def __call__(self, request_pid, kind, arg, dest, size):
            assert (request_pid, kind, arg) == (pid, 3, 0)
            # Offset is read from XNU proc_bsdinfo in the probe; validates the same layout.
            ctypes.c_uint32.from_address(ctypes.addressof(dest._obj) + 12).value = pid
            ctypes.c_uint64.from_address(ctypes.addressof(dest._obj) + size - 16).value = start
            return size

    class Library:
        proc_pidinfo = ProcInfo()

    monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: Library())
    monkeypatch.setattr(info.time, 'time', lambda: start + 25)
    assert info._ios_process_start() == start
    monkeypatch.setattr(ctypes, 'CDLL', real_cdll)


def test_ios_optional_metrics_fail_without_breaking_others(monkeypatch):
    from client.commands.platform.utils import ios_util
    from client.monitor import ios_dashboard
    monkeypatch.setattr(info, '_ios_process_start', lambda: (_ for _ in ()).throw(PermissionError('denied')))
    monkeypatch.setattr(info, '_ios_os_build', lambda version: None)
    monkeypatch.setattr(ios_dashboard, '_system_memory', lambda: (_ for _ in ()).throw(OSError('VM info denied')))
    monkeypatch.setattr(ios_util, 'get_ios_process_info', lambda: {
        'physical_memory_bytes': 8_589_934_592, 'system_uptime_seconds': 60,
    })
    monkeypatch.setattr(ios_util, 'get_ios_device_info', dict)
    monkeypatch.setattr(ios_util, 'get_ios_bundle_info', dict)
    monkeypatch.setattr(ios_util, 'read_info_plist', lambda: {})
    monkeypatch.setattr(ios_util, 'get_icloud_path', lambda info: None)
    fields = info.collect_ios(None)
    assert fields['mem_total'] == '8.00 GB'
    assert fields['mem_avail'] is None
    assert fields['process_start_time'] is None
    assert fields['process_uptime'] is None
    assert fields['os_build'] is None


def test_windows_process_launch_command_preserves_quoted_arguments(monkeypatch):
    import subprocess
    argv = [r'C:\Program Files\Python\python.exe', r'C:\RCH Client\rchclient.py',
            '--update-ready-file', r'C:\RCH Data\ready file.json']
    monkeypatch.setattr(info, 'os', SimpleNamespace(name='nt'))
    assert info._process_launch_command(SimpleNamespace(cmdline=lambda: argv)) == subprocess.list2cmdline(argv)



def test_os_product_names_for_macos_release_without_marketing_lookup():
    for version in ('13.5', '14.7.2', '15.1', '26.1', '28.0', '10.11.6'):
        identity = SimpleNamespace(os_alias='mac', os_version=version)
        assert info._base_os_product(identity) == f'macOS {version}'
    assert info._base_os_product(SimpleNamespace(os_alias='mac', os_version='')) == 'macOS'


def test_windows_local_caption_and_display_version(monkeypatch):
    # Windows 11 registry ProductName commonly remains Windows 10.
    assert info._windows_os_product({
        'ProductName': 'Windows 10 Pro', 'DisplayVersion': '25H2',
        'InstallationType': 'Client',
    }, 'Microsoft Windows 11 Pro') == 'Windows 11 Pro 25H2'
    assert info._windows_os_product({
        'ProductName': 'Windows 10 Pro', 'DisplayVersion': '25H2',
        'InstallationType': 'Client',
    }, None) == 'Windows 25H2'
    assert info._windows_os_product({'DisplayVersion': '27H2'},
                                    'Microsoft Windows 11 Enterprise') == 'Windows 11 Enterprise 27H2'


def test_read_windows_caption_uses_local_cim_with_timeout(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='Microsoft Windows 11 Pro\n')

    monkeypatch.setattr(info.subprocess, 'run', run)
    info._read_windows_os_caption.cache_clear()
    try:
        assert info._read_windows_os_caption() == 'Microsoft Windows 11 Pro'
        assert info._read_windows_os_caption() == 'Microsoft Windows 11 Pro'
        assert len(calls) == 1  # Static OS caption is cached per Client process.
        assert calls[0][0][0] == 'powershell.exe'
        assert 'Get-CimInstance' in calls[0][0][-1]
        assert calls[0][1]['timeout'] == 8
        assert calls[0][1]['check'] is False
    finally:
        info._read_windows_os_caption.cache_clear()


def test_read_windows_caption_fails_soft(monkeypatch):
    import subprocess
    info._read_windows_os_caption.cache_clear()
    monkeypatch.setattr(info.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(
        subprocess.TimeoutExpired('powershell', 8)))
    try:
        assert info._read_windows_os_caption() is None
    finally:
        info._read_windows_os_caption.cache_clear()


def test_windows_server_product_detection_and_fallback(monkeypatch):
    from client.commands.platform import utils as platform_utils
    fake_win_util = SimpleNamespace(
        get_windows_uid_gid_sid=lambda: {},
        get_locale_tag=lambda: 'en-US',
        get_integrity_level=lambda: 'High',
    )
    monkeypatch.setattr(platform_utils, 'win_util', fake_win_util, raising=False)
    monkeypatch.setattr(info.platform, 'processor', lambda: 'Intel64')
    monkeypatch.setattr(info, '_read_windows_current_version', lambda: {
        'ProductName': 'Windows Server 2025 Datacenter',
        'DisplayVersion': '24H2',
        'CurrentBuildNumber': '26100',
        'InstallationType': 'Server',
        'EditionID': 'ServerDatacenter',
    })
    monkeypatch.setattr(info, '_read_windows_os_caption',
                        lambda: 'Microsoft Windows Server 2025 Datacenter')
    fields = info.collect_windows(None)
    assert fields['os_product'] == 'Windows Server 2025 Datacenter'
    assert fields['os_build'] == '26100'

    monkeypatch.setattr(info, '_read_windows_current_version', lambda: {
        'ProductName': 'Windows 10 Enterprise',
        'CurrentBuildNumber': '26100',
        'InstallationType': 'Server Core',
        'EditionID': 'ServerStandard',
    })
    monkeypatch.setattr(info, '_read_windows_os_caption', lambda: None)
    fields = info.collect_windows(None)
    assert fields['os_product'] == 'Windows Server'


def test_windows_registry_reader_uses_native_64_bit_view(monkeypatch):
    import sys
    calls = []
    values = {
        'ProductName': 'Windows 10 Pro',
        'DisplayVersion': '25H2',
        'CurrentBuildNumber': '26200',
        'InstallationType': 'Client',
        'EditionID': 'Professional',
    }

    class WinReg:
        HKEY_LOCAL_MACHINE = object()
        KEY_READ = 0x20019
        KEY_WOW64_64KEY = 0x0100

        @staticmethod
        def OpenKey(root, path, reserved, access):
            calls.append(('open', root, path, reserved, access))
            return 'key'

        @staticmethod
        def QueryValueEx(key, name):
            calls.append(('query', key, name))
            if name not in values:
                raise OSError(name)
            return values[name], 1

        @staticmethod
        def CloseKey(key):
            calls.append(('close', key))

    monkeypatch.setitem(sys.modules, 'winreg', WinReg)
    result = info._read_windows_current_version()
    assert result == values
    assert calls[0][2] == r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    assert calls[0][4] == WinReg.KEY_READ | WinReg.KEY_WOW64_64KEY
    assert calls[-1] == ('close', 'key')


def test_apple_model_mapping_is_display_only_and_unknown_falls_back():
    from core.device.apple_models import resolve_apple_model_name
    assert resolve_apple_model_name('Mac14,2') == 'MacBook Air (M2, 2022)'
    assert resolve_apple_model_name('iPhone17,3') == 'iPhone 16'
    assert resolve_apple_model_name('iPad17,1') == 'iPad Pro 11-inch (M5)'
    assert resolve_apple_model_name('iPhone19,2') == 'iPhone 18 Pro'
    assert resolve_apple_model_name('iPhone19,4') == 'iPhone Duo'
    assert resolve_apple_model_name('Mac99,1') == 'Mac99,1'
    assert resolve_apple_model_name(None) is None


def test_getinfo_maps_apple_model_without_mutating_identity(monkeypatch):
    identity = SimpleNamespace(os_alias='ios', os_name='iOS', os_version='18.1.1',
                               arch='arm64', manufacturer='Apple', model='iPhone17,3',
                               hostname='localhost')
    monkeypatch.setattr(info, 'get_local_identity', lambda: identity)
    monkeypatch.setitem(info.COLLECTORS, 'ios', lambda owner: {})
    monkeypatch.setattr(info, 'get_executable_path', lambda: '/python app.py')
    result = info.getinfo(SimpleNamespace(_checkpoint=lambda: None))
    assert result.data['os_product'] == 'iOS 18.1.1'
    assert result.data['model'] == 'iPhone 16'
    assert identity.model == 'iPhone17,3'



def test_linux_pretty_name_becomes_common_os_product(monkeypatch):
    def read(path):
        if path == '/etc/os-release':
            return 'NAME="Ubuntu"\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04.3 LTS"\nBUILD_ID="2026.11.18"'
        return ''
    monkeypatch.setattr(info, '_read', read)
    fields = info.collect_linux(None)
    assert fields['os_product'] == 'Ubuntu 22.04.3 LTS'
    assert fields['os_build'] == '2026.11.18'
    assert 'distro_pretty_name' not in fields


def test_getinfo_maps_macos_model_name(monkeypatch):
    identity = SimpleNamespace(os_alias='mac', os_name='macOS', os_version='13.5',
                               arch='arm64', manufacturer='Apple', model='Mac14,2',
                               hostname='mac-host')
    monkeypatch.setattr(info, 'get_local_identity', lambda: identity)
    monkeypatch.setitem(info.COLLECTORS, 'mac', lambda owner: {})
    monkeypatch.setattr(info, 'get_executable_path', lambda: '/python client.py')
    result = info.getinfo(SimpleNamespace(_checkpoint=lambda: None))
    assert result.data['os_product'] == 'macOS 13.5'
    assert result.data['model'] == 'MacBook Air (M2, 2022)'
    assert identity.model == 'Mac14,2'



def test_ipad_getinfo_product_uses_ipados_name(monkeypatch):
    from client.commands.platform.utils import ios_util
    from client.monitor import ios_dashboard
    monkeypatch.setattr(info, '_ios_process_start', lambda: None)
    monkeypatch.setattr(ios_dashboard, '_system_memory', lambda: {'free': 0, 'inactive': 0})
    monkeypatch.setattr(ios_util, 'get_ios_process_info', lambda: {
        'physical_memory_bytes': 8_000_000_000, 'system_uptime_seconds': 100,
        'operating_system_version_string': 'Version 18.1.1 (Build 22B91)',
    })
    monkeypatch.setattr(ios_util, 'get_ios_device_info', lambda: {
        'device_type': 'Pad', 'system_version': '18.1.1', 'machine_name': 'iPad17,1',
    })
    monkeypatch.setattr(ios_util, 'get_ios_bundle_info', dict)
    monkeypatch.setattr(ios_util, 'read_info_plist', dict)
    monkeypatch.setattr(ios_util, 'get_icloud_path', lambda _: None)
    assert info.collect_ios(None)['os_product'] == 'iPadOS 18.1.1'
