import ctypes
import json
from types import SimpleNamespace
from unittest.mock import patch

import core.device.machine_identity as machine_identity


class _FakeSysctlFunction:
    argtypes = None
    restype = None

    def __call__(self, _name, old_value, old_length, _new_value, _new_length):
        payload = b'MacBookPro18,3\0'
        ctypes.memmove(old_value, payload, len(payload))
        ctypes.cast(old_length, ctypes.POINTER(ctypes.c_size_t)).contents.value = len(payload)
        return 0


class _FakeLibSystem:
    sysctlbyname = _FakeSysctlFunction()


def test_macos_model_uses_native_sysctlbyname_without_path_lookup():
    with patch.object(machine_identity.ctypes, 'CDLL', return_value=_FakeLibSystem()):
        assert machine_identity._read_macos_sysctl_value('hw.model') == 'MacBookPro18,3'


def test_macos_model_falls_back_to_absolute_sysctl_path_and_manufacturer_stays_apple():
    with patch.object(machine_identity.ctypes, 'CDLL', side_effect=OSError('no symbol')), patch.object(
        machine_identity, '_run_command_output', return_value='MacBookPro18,3'
    ) as run_command:
        assert machine_identity._detect_macos_manufacturer_and_model() == ('Apple', 'MacBookPro18,3')
    run_command.assert_called_once_with(['/usr/sbin/sysctl', '-n', 'hw.model'])


def test_windows_bios_registry_values_are_used_without_external_commands():
    with patch.object(machine_identity, '_read_windows_bios_registry_value', side_effect=['Lenovo', 'ThinkPad X1']), patch.object(
        machine_identity, '_query_windows_computer_system'
    ) as query:
        assert machine_identity._detect_windows_manufacturer_and_model() == ('Lenovo', 'ThinkPad X1')
    query.assert_not_called()


def test_windows_uses_cim_when_registry_values_are_missing():
    with patch.object(machine_identity, '_read_windows_bios_registry_value', return_value=''), patch.object(
        machine_identity, '_query_windows_computer_system', return_value=('Dell Inc.', 'XPS 13')
    ) as query:
        assert machine_identity._detect_windows_manufacturer_and_model() == ('Dell Inc.', 'XPS 13')
    query.assert_called_once_with()


def test_windows_cim_fallback_uses_powershell_and_parses_json_not_wmic():
    result = SimpleNamespace(returncode=0, stdout=json.dumps({'Manufacturer': 'Dell Inc.', 'Model': 'XPS 13'}))
    with patch.object(machine_identity.shutil, 'which', side_effect=lambda name: r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' if name == 'powershell.exe' else None), patch.object(
        machine_identity.subprocess, 'run', return_value=result
    ) as run:
        assert machine_identity._query_windows_computer_system() == ('Dell Inc.', 'XPS 13')
    args = run.call_args.args[0]
    assert args[0].endswith('powershell.exe')
    assert 'Get-CimInstance -ClassName Win32_ComputerSystem' in args[-1]
    assert 'wmic' not in args[-1].lower()


def test_generic_firmware_placeholders_are_treated_as_missing_values():
    assert machine_identity._clean_hardware_identity_value('To Be Filled By O.E.M.') == ''
    assert machine_identity._clean_hardware_identity_value('System Product Name') == ''
    assert machine_identity._clean_hardware_identity_value('MacBookPro18,3') == 'MacBookPro18,3'
