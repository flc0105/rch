"""getinfo field policy, lightweight acquisition and four-platform extensions."""

import json
import os
import sys
import time
from types import SimpleNamespace

import pytest

from client.commands.runtime.hosts import MacCommands, WindowsCommands, LinuxCommands, iOSCommands
from client.commands.shell.standalone import getinfo as info
from client.commands.shell.standalone import getinfo_collectors as probe
from core.device.apple_models import (
    resolve_apple_model_name, resolve_apple_chip_name, resolve_macos_product,
)
from core.utils.command_output import StructuredCommandResult, render_structured_result
from core.utils.formatting import seconds_to_readable_text


def _identity(alias):
    return SimpleNamespace(os_alias=alias, os_name='Test OS', os_version='13.5',
                           arch='arm64', manufacturer='Apple', model='Mac14,2', hostname='unit')


@pytest.fixture
def fake_snapshot(monkeypatch):
    monkeypatch.setattr(info, '_client_build', lambda: ('v20261119', 'rev20261119'))
    monkeypatch.setattr(info, 'get_executable_path', lambda: '/python client.py')
    monkeypatch.setattr(info, '_process_launch_command', lambda _: '/python client.py')
    monkeypatch.setattr(info, 'get_local_identity', lambda: _identity('linux'))


def _command(arg=''):
    return info.getinfo(SimpleNamespace(_checkpoint=lambda: None), arg)


@pytest.mark.parametrize('cls', [MacCommands, WindowsCommands, LinuxCommands, iOSCommands])
def test_single_common_registration(cls):
    handler = cls(None).getinfo
    assert handler.__func__ is info.getinfo
    assert handler.group == 'system'


@pytest.mark.parametrize('alias', ['mac', 'win', 'linux', 'ios'])
def test_default_and_all_common_schema(monkeypatch, fake_snapshot, alias):
    monkeypatch.setattr(info, 'get_local_identity', lambda: _identity(alias))
    monkeypatch.setitem(info.COLLECTORS, alias, lambda owner, *, detailed: {
        'cpu_model': 'CPU from hardware', 'gpu_models': ['GPU A', 'GPU B'],
        'os_product': 'Detailed OS', 'default_shell': '/bin/zsh',
        'kernel': 'Windows NT 10.0.26200' if alias == 'win' else 'Darwin 26',
        'device_name': 'Test device',
    })
    default = _command()
    full = _command('--all')
    short = _command('-a')
    assert isinstance(default, StructuredCommandResult)
    assert list(default.data) == list(info._output_data(default.data, alias, detailed=False))
    assert list(full.data) == list(info._output_data(full.data, alias, detailed=True))
    assert short.data == full.data
    assert set(default.data) < set(full.data)
    assert 'gpu_models' not in default.data
    assert full.data['gpu_models'] == ['GPU A', 'GPU B']
    assert default.data['cpu_model'] == 'CPU from hardware'
    assert full.data['cpu_model'] == 'CPU from hardware'
    assert default.data['rch_build_ver'] == 'v20261119'
    assert default.data['rch_build_revision'] == 'rev20261119'
    assert 'kernel' in default.data
    assert 'integrity' in default.data if alias == 'win' else 'integrity' not in default.data
    assert ('bundle_path' in full.data) == (alias == 'ios')
    assert ('default_shell_ver' in default.data) == (alias in ('mac', 'linux'))
    assert json.loads(render_structured_result(full, output_format='json')[1])['gpu_models'] == ['GPU A', 'GPU B']
    assert _command('--all --invalid') == (0, 'Usage: getinfo [-a|--all] [--json]')


def test_compact_duration_is_preserved():
    assert seconds_to_readable_text(0, compact=True) == '0s'
    assert seconds_to_readable_text(125, compact=True) == '2m 5s'
    assert seconds_to_readable_text(3605, compact=True) == '1h 0m 5s'


def test_apple_tables_and_unknown_model():
    assert resolve_apple_model_name('Mac14,2') == 'MacBook Air (M2, 2022)'
    assert resolve_apple_model_name('iPhone17,3') == 'iPhone 16'
    assert resolve_apple_chip_name('iPhone17,3') == 'Apple A18'
    assert resolve_apple_chip_name('iPhone16,1') == 'Apple A17 Pro'
    assert resolve_apple_chip_name('iPhone19,2') == 'Apple A20 Pro'
    assert resolve_apple_chip_name('iPhone19,4') == 'Apple A20 Pro'
    assert resolve_apple_chip_name('iPad16,1') == 'Apple A17 Pro'
    assert resolve_apple_chip_name('iPad17,1') == 'Apple M5'
    assert resolve_apple_chip_name('iPhone99,1') is None
    assert resolve_macos_product('13.5') == 'macOS Ventura 13.5'
    assert resolve_macos_product('27.0.1') == 'macOS Golden Gate 27.0.1'
    assert resolve_macos_product('999.1') == 'macOS 999.1'


def test_mac_default_does_not_collect_gpu_or_build(monkeypatch):
    called = []
    def command(command, timeout):
        called.append(command)
        return SimpleNamespace(returncode=0, stdout='Apple M2\n')
    owner = SimpleNamespace(process_execution_service=SimpleNamespace(run_shell_command=command))
    monkeypatch.setattr(probe, '_default_shell', lambda: '/bin/zsh')
    monkeypatch.setattr(probe, '_default_shell_version', lambda shell: 'zsh 5.9')
    data = probe.collect_mac(owner)
    assert data == {'cpu_model': 'Apple M2', 'default_shell': '/bin/zsh',
                    'default_shell_ver': 'zsh 5.9'}
    assert called == ['sysctl -n machdep.cpu.brand_string']
    monkeypatch.setattr(probe, '_mac_gpu_models', lambda owner: ['Apple M2'])
    data = probe.collect_mac(owner, detailed=True)
    assert data['os_build'] == 'Apple M2'
    assert data['gpu_models'] == ['Apple M2']
    assert called[-1] == 'sw_vers -buildVersion'


def test_linux_default_skips_gpu_and_optional_release(monkeypatch):
    reads = []
    def read(path):
        reads.append(path)
        return 'model name : Test CPU' if path == '/proc/cpuinfo' else 'PRETTY_NAME="Ubuntu 22.04 LTS"\nBUILD_ID="123"'
    monkeypatch.setattr(probe, '_read', read)
    monkeypatch.setattr(probe, '_default_shell', lambda: '/bin/bash')
    monkeypatch.setattr(probe, '_default_shell_version', lambda _: 'GNU bash 5.2')
    monkeypatch.setattr(probe, '_linux_gpu_models', lambda: ['Test GPU'])
    default = probe.collect_linux(None)
    assert default['cpu_model'] == 'Test CPU'
    assert reads == ['/proc/cpuinfo']
    assert not ({'has_desktop', 'package_manager', 'gpu_models', 'os_product'} & default.keys())
    full = probe.collect_linux(None, detailed=True)
    assert full['os_product'] == 'Ubuntu 22.04 LTS'
    assert full['os_build'] == '123'
    assert full['gpu_models'] == ['Test GPU']
    assert not ({'has_desktop', 'package_manager'} & full.keys())


def test_shell_version_is_login_shell_not_process_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(probe.subprocess, 'run', lambda argv, **kw:
                        calls.append(argv) or SimpleNamespace(returncode=0, stdout='zsh 5.9\n'))
    assert probe._default_shell_version('/bin/zsh') == 'zsh 5.9'
    assert calls == [['/bin/zsh', '--version']]


def test_windows_default_registry_cpu_no_powershell_or_wmi(monkeypatch):
    from client.commands.platform import utils as platform_utils
    monkeypatch.setattr(platform_utils, 'win_util', SimpleNamespace(
        get_integrity_level=lambda: 'Medium',
        get_windows_uid_gid_sid=lambda: pytest.fail('SIDs must not be read by default'),
        get_locale_tag=lambda: pytest.fail('Locale must not be read by default'),
    ), raising=False)
    monkeypatch.setattr(probe, '_read_windows_current_version', lambda: {'CurrentBuildNumber': '26200', 'UBR': 9974})
    monkeypatch.setattr(probe, '_windows_nt_version', lambda registry: 'Windows NT 10.0.26200.9974')
    monkeypatch.setattr(probe, '_windows_processor_name_from_registry', lambda: 'Intel Core i5-8250U')
    monkeypatch.setattr(probe, '_windows_brand', lambda: pytest.fail('brand is full-only'))
    monkeypatch.setattr(probe, '_read_windows_hardware', lambda: pytest.fail('CIM is full-only'))
    monkeypatch.setattr(probe.subprocess, 'run', lambda *a, **kw: pytest.fail('No subprocess in Windows default'))
    result = probe.collect_windows(None)
    assert result == {'cpu_model': 'Intel Core i5-8250U',
                      'kernel': 'Windows NT 10.0.26200.9974', 'integrity': 'Medium'}


def test_windows_full_fields_and_enabled_pci_gpu(monkeypatch):
    from client.commands.platform import utils as platform_utils
    monkeypatch.setattr(platform_utils, 'win_util', SimpleNamespace(
        get_integrity_level=lambda: 'High',
        get_windows_uid_gid_sid=lambda: {'uid': 'S-1-user', 'gid': 'S-1-group'},
        get_locale_tag=lambda: 'en-US',
    ), raising=False)
    monkeypatch.setattr(probe, '_read_windows_current_version', lambda: {
        'DisplayVersion':'25H2', 'CurrentBuildNumber':'26200', 'UBR':9974,
    })
    monkeypatch.setattr(probe, '_windows_nt_version', lambda _: 'Windows NT 10.0.26200.9974')
    monkeypatch.setattr(probe, '_windows_processor_name_from_registry', lambda: 'AMD Ryzen 9')
    monkeypatch.setattr(probe, '_windows_brand', lambda: 'Windows 11 Home')
    monkeypatch.setattr(probe, '_read_windows_hardware', lambda: {
        'gpu_models': ['Intel UHD Graphics 620', 'Intel UHD Graphics 620'],
    })
    fields = probe.collect_windows(None, detailed=True)
    assert fields['os_product'] == 'Windows 11 Home 25H2'
    assert fields['os_build'] == '26200'
    assert fields['gpu_models'] == ['Intel UHD Graphics 620']
    assert (fields['integrity'], fields['locale'], fields['user_sid'], fields['group_sid']) == (
        'High','en-US','S-1-user','S-1-group')
    assert fields['cpu_model'] == 'AMD Ryzen 9'


def test_windows_gpu_cim_still_filters_enabled_pci_devices(monkeypatch):
    probe._read_windows_hardware.cache_clear()
    commands = []
    def run(argv, **kwargs):
        commands.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'gpu_models': ['Intel UHD Graphics 620', 'AMD Radeon'],
        }))
    monkeypatch.setattr(probe.subprocess, 'run', run)
    try:
        data = probe._read_windows_hardware()
        assert data['gpu_models'] == ['Intel UHD Graphics 620', 'AMD Radeon']
        assert len(commands) == 1
        script = commands[0][0][-1]
        assert 'Win32_VideoController' in script
        assert 'Win32_Processor' not in script
        assert r"$_.PNPDeviceID -match '^PCI\\VEN_' -and $_.ConfigManagerErrorCode -eq 0" in script
        assert commands[0][1]['timeout'] == 12
        assert probe._read_windows_hardware() is data
    finally:
        probe._read_windows_hardware.cache_clear()


def test_windows_registry_cpu_reads_processor_name_string(monkeypatch):
    class WinReg:
        HKEY_LOCAL_MACHINE = 'HKLM'
        @staticmethod
        def OpenKey(root, path):
            assert path == r'HARDWARE\DESCRIPTION\System\CentralProcessor\0'
            return 'key'
        @staticmethod
        def QueryValueEx(key, name):
            assert name == 'ProcessorNameString'
            return ('Intel Core i7', 1)
    class Key:
        def __enter__(self): return 'key'
        def __exit__(self, *args): pass
    WinReg.OpenKey = staticmethod(lambda root, path: Key())
    monkeypatch.setitem(sys.modules, 'winreg', WinReg)
    assert probe._windows_processor_name_from_registry() == 'Intel Core i7'


def test_windows_brand_is_freed(monkeypatch):
    class Function:
        def __init__(self, output): self.output = output; self.calls = []
        def __call__(self, *args): self.calls.append(args); return self.output
    branding = Function(123)
    free = Function(None)
    monkeypatch.setattr(probe.ctypes, 'WinDLL', lambda name, **kw:
                        SimpleNamespace(BrandingFormatString=branding) if name=='winbrand.dll'
                        else SimpleNamespace(GlobalFree=free), raising=False)
    monkeypatch.setattr(probe.ctypes, 'wstring_at', lambda ptr: 'Windows 11 Home')
    probe._windows_brand.cache_clear()
    try:
        assert probe._windows_brand() == 'Windows 11 Home'
        assert branding.calls == [('%WINDOWS_LONG%',)]
        assert free.calls == [(123,)]
    finally:
        probe._windows_brand.cache_clear()


def test_ios_default_and_full_native_data(monkeypatch):
    from client.commands.platform.utils import ios_util
    from client.monitor import ios_dashboard
    observed = []
    now = time.time()
    monkeypatch.setattr(probe, '_ios_process_start', lambda: now - 100)
    monkeypatch.setattr(ios_dashboard, '_system_memory', lambda: {'free':1024, 'inactive':2048})
    monkeypatch.setattr(ios_util, 'get_ios_process_info', lambda: {
        'process_name':'Pythonista', 'processor_count': 6, 'physical_memory_bytes':8192,
        'username':'mobile', 'system_uptime_seconds': 3600,
        'operating_system_version_string':'Version 27.0 (Build 24A1)',
    })
    monkeypatch.setattr(ios_util, 'get_ios_device_info', lambda: {
        'machine_name':'iPhone17,3', 'device_name':'iPhone', 'device_model':'iPhone',
        'device_type':'Phone', 'identifier_for_vendor':'device-id',
    })
    monkeypatch.setattr(ios_util, 'get_ios_bundle_info', lambda: {
        'app_name':'Pythonista', 'bundle_identifier':'app.pythonista',
    })
    monkeypatch.setattr(ios_util, 'read_info_plist', lambda: observed.append('plist') or {})
    monkeypatch.setattr(ios_util, 'get_icloud_path', lambda _: observed.append('icloud') or '/cloud')
    monkeypatch.setattr(probe, '_ios_os_build', lambda _: observed.append('osbuild') or '24A1')
    default = probe.collect_ios(None)
    assert default['cpu_model'] == 'Apple A18'
    assert default['app_name'] == 'Pythonista'
    assert default['mem_avail'] is not None
    assert not observed
    assert 'bundle_path' not in default
    full = probe.collect_ios(None, detailed=True)
    assert full['os_build'] == '24A1'
    assert full['icloud'] == '/cloud'
    assert full['system_boot_time'] is not None
    assert 'osbuild' in observed and 'icloud' in observed


@pytest.mark.parametrize('alias', ['win', 'mac', 'linux', 'ios'])
def test_getinfo_field_order_and_detail_insertion(alias):
    common_os = ['os_name', 'os_version']
    common_hardware = ['kernel', 'arch', 'manufacturer', 'model', 'hostname',
                       'cpu_model', 'cpu_count', 'mem_total', 'mem_avail']
    common_process = ['pid', 'ppid', 'process_name']
    common_end = ['rch_build_ver', 'rch_build_revision']
    platform_shell = ['default_shell', 'default_shell_ver'] if alias in ('mac', 'linux') else []
    ios_default = ['device_name', 'device_model', 'device_type', 'app_name', 'bundle_identifier'] if alias == 'ios' else []
    ios_detail = (['device_name', 'device_model', 'device_type', 'machine_name',
                   'identifier_for_vendor', 'app_name', 'bundle_name', 'bundle_identifier',
                   'bundle_path', 'bundle_executable_path', 'bundle_version',
                   'bundle_short_version', 'low_power_mode_enabled', 'home',
                   'documents', 'temp', 'icloud'] if alias == 'ios' else [])
    def expected(detailed):
        return (common_os + (['os_build', 'os_product'] if detailed else []) +
                common_hardware + (['gpu_models'] if detailed else []) +
                ['username'] + (['integrity'] if alias == 'win' else []) +
                common_process + (['launch_command', 'system_boot_time'] if detailed else []) +
                ['system_uptime'] + (['process_start_time'] if detailed else []) +
                ['process_uptime'] + platform_shell +
                (['locale', 'user_sid', 'group_sid'] if alias == 'win' and detailed else []) +
                ['python_version'] + (ios_detail if detailed else ios_default) + common_end)
    for detailed in (False, True):
        values = info._output_data({}, alias, detailed=detailed)
        assert list(values) == expected(detailed)
        text = render_structured_result(StructuredCommandResult(
            status=1, data=values, shape='dict', width=24, null_text='N/A'))[1]
        assert [line.split()[0] for line in text.splitlines()] == expected(detailed)
        encoded = render_structured_result(StructuredCommandResult(
            status=1, data=values, shape='dict', width=24), output_format='json')[1]
        assert list(json.loads(encoded)) == expected(detailed)


def test_mac_default_does_not_collect_gpu_or_build(monkeypatch):
    called = []
    def command(command, timeout):
        called.append(command)
        return SimpleNamespace(returncode=0, stdout='Apple M2\n')
    owner = SimpleNamespace(process_execution_service=SimpleNamespace(run_shell_command=command))
    monkeypatch.setattr(probe, '_default_shell', lambda: '/bin/zsh')
    monkeypatch.setattr(probe, '_default_shell_version', lambda shell: 'zsh 5.9')
    data = probe.collect_mac(owner)
    assert data == {'cpu_model': 'Apple M2', 'default_shell': '/bin/zsh',
                    'default_shell_ver': 'zsh 5.9'}
    assert called == ['sysctl -n machdep.cpu.brand_string']
    monkeypatch.setattr(probe, '_mac_gpu_models', lambda owner: ['Apple M2'])
    data = probe.collect_mac(owner, detailed=True)
    assert data['os_build'] == 'Apple M2'
    assert data['gpu_models'] == ['Apple M2']
    assert called[-1] == 'sw_vers -buildVersion'


def test_linux_default_skips_gpu_and_optional_release(monkeypatch):
    reads = []
    def read(path):
        reads.append(path)
        return 'model name : Test CPU' if path == '/proc/cpuinfo' else 'PRETTY_NAME="Ubuntu 22.04 LTS"\nBUILD_ID="123"'
    monkeypatch.setattr(probe, '_read', read)
    monkeypatch.setattr(probe, '_default_shell', lambda: '/bin/bash')
    monkeypatch.setattr(probe, '_default_shell_version', lambda _: 'GNU bash 5.2')
    monkeypatch.setattr(probe, '_linux_gpu_models', lambda: ['Test GPU'])
    default = probe.collect_linux(None)
    assert default['cpu_model'] == 'Test CPU'
    assert reads == ['/proc/cpuinfo']
    assert not ({'has_desktop', 'package_manager', 'gpu_models', 'os_product'} & default.keys())
    full = probe.collect_linux(None, detailed=True)
    assert full['os_product'] == 'Ubuntu 22.04 LTS'
    assert full['os_build'] == '123'
    assert full['gpu_models'] == ['Test GPU']
    assert not ({'has_desktop', 'package_manager'} & full.keys())


def test_shell_version_is_login_shell_not_process_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(probe.subprocess, 'run', lambda argv, **kw:
                        calls.append(argv) or SimpleNamespace(returncode=0, stdout='zsh 5.9\n'))
    assert probe._default_shell_version('/bin/zsh') == 'zsh 5.9'
    assert calls == [['/bin/zsh', '--version']]


def test_windows_default_registry_cpu_no_powershell_or_wmi(monkeypatch):
    from client.commands.platform import utils as platform_utils
    monkeypatch.setattr(platform_utils, 'win_util', SimpleNamespace(
        get_integrity_level=lambda: 'Medium',
        get_windows_uid_gid_sid=lambda: pytest.fail('SIDs must not be read by default'),
        get_locale_tag=lambda: pytest.fail('Locale must not be read by default'),
    ), raising=False)
    monkeypatch.setattr(probe, '_read_windows_current_version', lambda: {'CurrentBuildNumber': '26200', 'UBR': 9974})
    monkeypatch.setattr(probe, '_windows_nt_version', lambda registry: 'Windows NT 10.0.26200.9974')
    monkeypatch.setattr(probe, '_windows_processor_name_from_registry', lambda: 'Intel Core i5-8250U')
    monkeypatch.setattr(probe, '_windows_brand', lambda: pytest.fail('brand is full-only'))
    monkeypatch.setattr(probe, '_read_windows_hardware', lambda: pytest.fail('CIM is full-only'))
    monkeypatch.setattr(probe.subprocess, 'run', lambda *a, **kw: pytest.fail('No subprocess in Windows default'))
    result = probe.collect_windows(None)
    assert result == {'cpu_model': 'Intel Core i5-8250U',
                      'kernel': 'Windows NT 10.0.26200.9974', 'integrity': 'Medium'}


def test_windows_full_fields_and_enabled_pci_gpu(monkeypatch):
    from client.commands.platform import utils as platform_utils
    monkeypatch.setattr(platform_utils, 'win_util', SimpleNamespace(
        get_integrity_level=lambda: 'High',
        get_windows_uid_gid_sid=lambda: {'uid': 'S-1-user', 'gid': 'S-1-group'},
        get_locale_tag=lambda: 'en-US',
    ), raising=False)
    monkeypatch.setattr(probe, '_read_windows_current_version', lambda: {
        'DisplayVersion':'25H2', 'CurrentBuildNumber':'26200', 'UBR':9974,
    })
    monkeypatch.setattr(probe, '_windows_nt_version', lambda _: 'Windows NT 10.0.26200.9974')
    monkeypatch.setattr(probe, '_windows_processor_name_from_registry', lambda: 'AMD Ryzen 9')
    monkeypatch.setattr(probe, '_windows_brand', lambda: 'Windows 11 Home')
    monkeypatch.setattr(probe, '_read_windows_hardware', lambda: {
        'gpu_models': ['Intel UHD Graphics 620', 'Intel UHD Graphics 620'],
    })
    fields = probe.collect_windows(None, detailed=True)
    assert fields['os_product'] == 'Windows 11 Home 25H2'
    assert fields['os_build'] == '26200'
    assert fields['gpu_models'] == ['Intel UHD Graphics 620']
    assert (fields['integrity'], fields['locale'], fields['user_sid'], fields['group_sid']) == (
        'High','en-US','S-1-user','S-1-group')
    assert fields['cpu_model'] == 'AMD Ryzen 9'


def test_windows_gpu_cim_still_filters_enabled_pci_devices(monkeypatch):
    probe._read_windows_hardware.cache_clear()
    commands = []
    def run(argv, **kwargs):
        commands.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'gpu_models': ['Intel UHD Graphics 620', 'AMD Radeon'],
        }))
    monkeypatch.setattr(probe.subprocess, 'run', run)
    try:
        data = probe._read_windows_hardware()
        assert data['gpu_models'] == ['Intel UHD Graphics 620', 'AMD Radeon']
        assert len(commands) == 1
        script = commands[0][0][-1]
        assert 'Win32_VideoController' in script
        assert 'Win32_Processor' not in script
        assert r"$_.PNPDeviceID -match '^PCI\\VEN_' -and $_.ConfigManagerErrorCode -eq 0" in script
        assert commands[0][1]['timeout'] == 12
        assert probe._read_windows_hardware() is data
    finally:
        probe._read_windows_hardware.cache_clear()


def test_windows_registry_cpu_reads_processor_name_string(monkeypatch):
    class WinReg:
        HKEY_LOCAL_MACHINE = 'HKLM'
        @staticmethod
        def OpenKey(root, path):
            assert path == r'HARDWARE\DESCRIPTION\System\CentralProcessor\0'
            return 'key'
        @staticmethod
        def QueryValueEx(key, name):
            assert name == 'ProcessorNameString'
            return ('Intel Core i7', 1)
    class Key:
        def __enter__(self): return 'key'
        def __exit__(self, *args): pass
    WinReg.OpenKey = staticmethod(lambda root, path: Key())
    monkeypatch.setitem(sys.modules, 'winreg', WinReg)
    assert probe._windows_processor_name_from_registry() == 'Intel Core i7'


def test_windows_brand_is_freed(monkeypatch):
    class Function:
        def __init__(self, output): self.output = output; self.calls = []
        def __call__(self, *args): self.calls.append(args); return self.output
    branding = Function(123)
    free = Function(None)
    monkeypatch.setattr(probe.ctypes, 'WinDLL', lambda name, **kw:
                        SimpleNamespace(BrandingFormatString=branding) if name=='winbrand.dll'
                        else SimpleNamespace(GlobalFree=free), raising=False)
    monkeypatch.setattr(probe.ctypes, 'wstring_at', lambda ptr: 'Windows 11 Home')
    probe._windows_brand.cache_clear()
    try:
        assert probe._windows_brand() == 'Windows 11 Home'
        assert branding.calls == [('%WINDOWS_LONG%',)]
        assert free.calls == [(123,)]
    finally:
        probe._windows_brand.cache_clear()


def test_ios_default_and_full_native_data(monkeypatch):
    from client.commands.platform.utils import ios_util
    from client.monitor import ios_dashboard
    observed = []
    now = time.time()
    monkeypatch.setattr(probe, '_ios_process_start', lambda: now - 100)
    monkeypatch.setattr(ios_dashboard, '_system_memory', lambda: {'free':1024, 'inactive':2048})
    monkeypatch.setattr(ios_util, 'get_ios_process_info', lambda: {
        'process_name':'Pythonista', 'processor_count': 6, 'physical_memory_bytes':8192,
        'username':'mobile', 'system_uptime_seconds': 3600,
        'operating_system_version_string':'Version 27.0 (Build 24A1)',
    })
    monkeypatch.setattr(ios_util, 'get_ios_device_info', lambda: {
        'machine_name':'iPhone17,3', 'device_name':'iPhone', 'device_model':'iPhone',
        'device_type':'Phone', 'identifier_for_vendor':'device-id',
    })
    monkeypatch.setattr(ios_util, 'get_ios_bundle_info', lambda: {
        'app_name':'Pythonista', 'bundle_identifier':'app.pythonista',
    })
    monkeypatch.setattr(ios_util, 'read_info_plist', lambda: observed.append('plist') or {})
    monkeypatch.setattr(ios_util, 'get_icloud_path', lambda _: observed.append('icloud') or '/cloud')
    monkeypatch.setattr(probe, '_ios_os_build', lambda _: observed.append('osbuild') or '24A1')
    default = probe.collect_ios(None)
    assert default['cpu_model'] == 'Apple A18'
    assert default['app_name'] == 'Pythonista'
    assert default['mem_avail'] is not None
    assert not observed
    assert 'bundle_path' not in default
    full = probe.collect_ios(None, detailed=True)
    assert full['os_build'] == '24A1'
    assert full['icloud'] == '/cloud'
    assert full['system_boot_time'] is not None
    assert 'osbuild' in observed and 'icloud' in observed


def test_ios_ipad_product_only_in_all(monkeypatch):
    from client.commands.platform.utils import ios_util
    from client.monitor import ios_dashboard
    monkeypatch.setattr(probe, '_ios_process_start', lambda: None)
    monkeypatch.setattr(ios_dashboard, '_system_memory', lambda: None)
    monkeypatch.setattr(ios_util, 'get_ios_process_info', lambda: {})
    monkeypatch.setattr(ios_util, 'get_ios_device_info', lambda: {
        'device_type': 'Pad', 'system_version':'27.0', 'machine_name':'iPad17,1',
    })
    monkeypatch.setattr(ios_util, 'get_ios_bundle_info', lambda: {})
    monkeypatch.setattr(ios_util, 'read_info_plist', lambda: {})
    monkeypatch.setattr(ios_util, 'get_icloud_path', lambda _: None)
    assert 'os_product' not in probe.collect_ios(None)
    all_info = probe.collect_ios(None, detailed=True)
    assert all_info['os_product'] == 'iPadOS 27.0'
    assert all_info['cpu_model'] == 'Apple M5'


def test_gpu_models_text_and_json_are_stable():
    result = StructuredCommandResult(status=1, data={
        'gpu_models':['Integrated GPU', 'Dedicated GPU'], 'other':[2,3], 'missing':None,
    }, shape='dict', width=24, null_text='N/A')
    text = render_structured_result(result)[1]
    assert 'Integrated GPU, Dedicated GPU' in text
    assert "['Integrated GPU', 'Dedicated GPU']" not in text
    data = json.loads(render_structured_result(result, output_format='json')[1])
    assert data['gpu_models'] == ['Integrated GPU','Dedicated GPU']


def test_linux_gpu_original_pci_parser(monkeypatch):
    sample = ('00:02.0 VGA compatible controller [0300]: Cirrus Logic GD 5446 [1013:00b8]\n'
              '01:00.0 3D controller [0302]: NVIDIA GA102 [GeForce RTX 3090] [10de:2204] (rev a1)\n')
    monkeypatch.setattr(probe.shutil, 'which', lambda cmd: '/usr/bin/lspci')
    monkeypatch.setattr(probe.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=sample))
    assert probe._linux_gpu_models() == ['Cirrus Logic GD 5446',
                                        'NVIDIA GA102 [GeForce RTX 3090] (rev a1)']
