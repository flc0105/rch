import ctypes
import hashlib
import json
import os
import platform
import re
import subprocess

from core.platform.platform_identity import PlatformAlias, detect_platform_info

MACHINE_ID_VERSION = 'v1'


def _safe_text(value, default='') -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def _run_command_output(command: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            return ''
        return (result.stdout or '').strip()
    except Exception:
        return ''


def _normalize_machine_fingerprint_value(value) -> str:
    text = _safe_text(value, '').strip().lower()
    if not text:
        return 'na'

    text = re.sub(r'\s+', '_', text)
    text = re.sub(r'[^a-z0-9._:-]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text or 'na'


def _normalize_os_version(value: str) -> str:
    text = _safe_text(value, '').strip()
    if not text:
        return 'na'

    match = re.search(r'\d+(?:\.\d+)+', text)
    if match:
        return _normalize_machine_fingerprint_value(match.group(0))

    match = re.search(r'\d+', text)
    if match:
        return _normalize_machine_fingerprint_value(match.group(0))

    return _normalize_machine_fingerprint_value(text)


def _read_first_existing_text_file(paths: list[str]) -> str:
    for path in paths:
        try:
            if os.path.isfile(path):
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read().strip()
        except Exception:
            continue
    return ''


def _detect_ios_arch() -> str:
    try:
        libc = ctypes.CDLL(None)
        size = ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
        value = ctypes.c_int()

        result = libc.sysctlbyname(
            b'hw.optional.arm64',
            ctypes.byref(value),
            ctypes.byref(size),
            None,
            0,
        )
        if result == 0 and value.value == 1:
            return 'arm64'
    except Exception:
        pass

    return 'na'


def _read_linux_os_release() -> dict:
    content = _read_first_existing_text_file([
        '/etc/os-release',
        '/usr/lib/os-release',
    ])

    data = {}
    if not content:
        return data

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value

    return data


def _detect_linux_distribution_name_and_version() -> tuple[str, str]:
    os_release = _read_linux_os_release()

    os_name = (
            _safe_text(os_release.get('NAME')).strip()
            or _safe_text(os_release.get('ID')).strip()
            or 'Linux'
    )

    os_version = (
            _safe_text(os_release.get('VERSION_ID')).strip()
            or _safe_text(os_release.get('VERSION')).strip()
            or _safe_text(platform.release()).strip()
            or _safe_text(platform.version()).strip()
    )

    return os_name, os_version


def _detect_windows_manufacturer_and_model() -> tuple[str, str]:
    try:
        output = _run_command_output(['wmic', 'computersystem', 'get', 'manufacturer,model', '/value'])
        manufacturer = ''
        model = ''
        for line in output.splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip().lower()
            value = value.strip()
            if key == 'manufacturer' and value:
                manufacturer = value
            elif key == 'model' and value:
                model = value
        return manufacturer, model
    except Exception:
        return '', ''


def _detect_windows_native_id() -> str:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography')
        value, _ = winreg.QueryValueEx(key, 'MachineGuid')
        return _safe_text(value).strip()
    except Exception:
        return ''


def _detect_macos_manufacturer_and_model() -> tuple[str, str]:
    manufacturer = 'Apple'
    model = _run_command_output(['sysctl', '-n', 'hw.model'])
    return manufacturer, model


def _detect_macos_native_id() -> str:
    output = _run_command_output(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'])
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
    if match:
        return match.group(1).strip()
    return ''


def _detect_linux_manufacturer_and_model() -> tuple[str, str]:
    manufacturer = _read_first_existing_text_file([
        '/sys/devices/virtual/dmi/id/sys_vendor',
        '/sys/class/dmi/id/sys_vendor',
    ])
    model = _read_first_existing_text_file([
        '/sys/devices/virtual/dmi/id/product_name',
        '/sys/class/dmi/id/product_name',
    ])
    return manufacturer, model


def _detect_linux_native_id() -> str:
    return _read_first_existing_text_file([
        '/etc/machine-id',
        '/var/lib/dbus/machine-id',
    ])


def _detect_ios_manufacturer_and_model() -> tuple[str, str]:
    manufacturer = 'Apple'
    model = ''
    try:
        import objc_util

        UIDevice = objc_util.ObjCClass('UIDevice')
        current_device = UIDevice.currentDevice()
        localized_model = _safe_text(current_device.localizedModel())
        model_name = _safe_text(current_device.model())
        model = platform.machine() or model_name or localized_model
    except Exception:
        pass
    return manufacturer, model


def _detect_ios_native_id() -> str:
    try:
        import objc_util

        UIDevice = objc_util.ObjCClass('UIDevice')
        current_device = UIDevice.currentDevice()
        vendor_identifier = current_device.identifierForVendor()
        if vendor_identifier:
            return _safe_text(vendor_identifier.UUIDString())
    except Exception:
        pass
    return ''


def _detect_os_display_version(platform_info) -> str:
    try:
        if platform_info.alias == PlatformAlias.MAC.value:
            version = platform.mac_ver()[0]
            if version:
                return version
        if platform_info.alias == PlatformAlias.IOS.value:
            try:
                import objc_util

                UIDevice = objc_util.ObjCClass('UIDevice')
                current_device = UIDevice.currentDevice()
                version = _safe_text(current_device.systemVersion())
                if version:
                    return version
            except Exception:
                pass
        if platform_info.alias == PlatformAlias.LINUX.value:
            _, version = _detect_linux_distribution_name_and_version()
            if version:
                return version
    except Exception:
        pass

    return _safe_text(platform.version() or platform.release() or '')


def detect_machine_identity_components(platform_info=None) -> dict:
    platform_info = platform_info or detect_platform_info()

    hostname = _safe_text(platform.node()).strip()
    os_name = platform_info.display_name
    os_version = ''
    if platform_info.alias == PlatformAlias.LINUX.value:
        os_name, os_version = _detect_linux_distribution_name_and_version()
    else:
        os_version = _detect_os_display_version(platform_info)

    arch = _safe_text(platform.machine()).strip()
    if platform_info.alias == PlatformAlias.IOS.value:
        arch = _detect_ios_arch()
    manufacturer = ''
    model = ''
    native_id = ''

    if platform_info.alias == PlatformAlias.WIN.value:
        manufacturer, model = _detect_windows_manufacturer_and_model()
        native_id = _detect_windows_native_id()
    elif platform_info.alias == PlatformAlias.MAC.value:
        manufacturer, model = _detect_macos_manufacturer_and_model()
        native_id = _detect_macos_native_id()
    elif platform_info.alias == PlatformAlias.LINUX.value:
        manufacturer, model = _detect_linux_manufacturer_and_model()
        native_id = _detect_linux_native_id()
    elif platform_info.alias == PlatformAlias.IOS.value:
        manufacturer, model = _detect_ios_manufacturer_and_model()
        native_id = _detect_ios_native_id()

    return {
        'hostname': hostname,
        'os_name': os_name,
        'os_version': os_version,
        'arch': arch,
        'manufacturer': manufacturer,
        'model': model,
        'native_id': native_id,
    }


def _detect_machine_identity_components() -> dict:
    # Backward-compatible private alias; new runtime code should use get_local_identity().
    return detect_machine_identity_components()


def build_machine_identity_payload(raw_components=None) -> dict:
    raw = dict(raw_components) if isinstance(raw_components, dict) else detect_machine_identity_components()

    normalized = {
        'hostname': _normalize_machine_fingerprint_value(raw.get('hostname')),
        'os_name': _normalize_machine_fingerprint_value(raw.get('os_name')),
        'os_version': _normalize_os_version(raw.get('os_version')),
        'arch': _normalize_machine_fingerprint_value(raw.get('arch')),
        'manufacturer': _normalize_machine_fingerprint_value(raw.get('manufacturer')),
        'model': _normalize_machine_fingerprint_value(raw.get('model')),
        'native_id': _normalize_machine_fingerprint_value(raw.get('native_id')),
    }

    fingerprint_basis = (
        f'{MACHINE_ID_VERSION}'
        f'|hostname={normalized["hostname"]}'
        f'|os_name={normalized["os_name"]}'
        f'|os_version={normalized["os_version"]}'
        f'|arch={normalized["arch"]}'
        f'|manufacturer={normalized["manufacturer"]}'
        f'|model={normalized["model"]}'
        f'|native_id={normalized["native_id"]}'
    )
    machine_id = hashlib.sha256(fingerprint_basis.encode('utf-8')).hexdigest()

    return {
        'machine_id_version': MACHINE_ID_VERSION,
        'machine_id_hash': machine_id,
        'machine_id_short': machine_id[:24],
        'fingerprint_basis': fingerprint_basis,
        'raw_components': raw,
        'normalized_components': normalized,
    }


def build_machine_identity_demo_text() -> str:
    payload = build_machine_identity_payload()
    return json.dumps(payload, ensure_ascii=False, indent=2)
