"""Best-effort chassis classification shared by handshake and RCH variables.

Classification follows the platform rules in the bundled detect_device.py recon
script; virtualization and model reporting are separate concerns.
"""

import json
import os
import platform
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


CHASSIS_TYPES = {
    3: 'desktop', 4: 'desktop', 5: 'desktop', 6: 'desktop',
    7: 'desktop', 13: 'desktop', 15: 'desktop',
    9: 'laptop', 10: 'laptop', 14: 'laptop',
    11: 'handheld', 17: 'server', 23: 'server', 28: 'server', 29: 'server',
    30: 'tablet', 31: 'convertible', 32: 'tablet',
}


def _chassis_type(codes) -> str:
    for code in codes:
        try:
            result = CHASSIS_TYPES.get(int(code))
        except (ValueError, TypeError):
            continue
        if result:
            return result
    return 'unknown'


def _run(*command, timeout=3) -> str:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=timeout, check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace').strip()
    except (OSError, UnicodeError):
        return ''


def _mac_chassis_type(value: str) -> str:
    name = value.lower().replace(' ', '')
    if 'macbook' in name:
        return 'laptop'
    if any(part in name for part in ('imac', 'macmini', 'macstudio', 'macpro')):
        return 'desktop'
    return 'unknown'


def _detect_chassis_type() -> str:
    system = platform.system()

    if system in ('iOS', 'iPadOS') or sys.platform == 'ios':
        if hasattr(platform, 'ios_ver'):
            try:
                model = str(platform.ios_ver().model or '').lower()
                if model.startswith('ipad'):
                    return 'tablet'
                if model.startswith('iphone'):
                    return 'phone'
            except (OSError, RuntimeError, AttributeError):
                pass
        try:
            import objc_util
            idiom = int(objc_util.ObjCClass('UIDevice').currentDevice().userInterfaceIdiom())
            if idiom == 1:
                return 'tablet'
            if idiom == 0:
                return 'phone'
        except Exception:
            pass
        return 'tablet' if system == 'iPadOS' else 'phone'

    android = (
        system == 'Android' or sys.platform == 'android'
        or hasattr(sys, 'getandroidapilevel')
        or ('ANDROID_ROOT' in os.environ and 'ANDROID_DATA' in os.environ)
    )
    if android:
        getprop = '/system/bin/getprop' if Path('/system/bin/getprop').exists() else 'getprop'
        characteristics = _run(getprop, 'ro.build.characteristics', timeout=1).lower().split(',')
        if 'tablet' in characteristics:
            return 'tablet'
        if 'phone' in characteristics:
            return 'phone'
        return 'mobile'

    if system == 'Windows':
        # Preserve the recon script's Win32_SystemEnclosure classification.
        script = (
            '[Console]::OutputEncoding=[Text.Encoding]::UTF8;'
            '$c=Get-CimInstance Win32_SystemEnclosure;'
            '@{chassis=@($c.ChassisTypes)} | ConvertTo-Json -Compress'
        )
        raw = _run('powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script)
        try:
            codes = json.loads(raw).get('chassis') or []
            return _chassis_type(codes if isinstance(codes, list) else [codes])
        except (ValueError, TypeError, AttributeError):
            return 'unknown'

    if system == 'Darwin':
        # The hardware model is cheap to read; system_profiler is a bounded fallback.
        model = _run('sysctl', '-n', 'hw.model', timeout=1)
        kind = _mac_chassis_type(model)
        if kind != 'unknown':
            return kind
        raw = _run('system_profiler', 'SPHardwareDataType', '-json')
        try:
            data = json.loads(raw)['SPHardwareDataType'][0]
            return _mac_chassis_type(str(data.get('machine_name') or ''))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return 'unknown'

    if system == 'Linux':
        return _chassis_type([_read('/sys/class/dmi/id/chassis_type')])

    return 'unknown'


@lru_cache(maxsize=1)
def get_chassis_type() -> str:
    """Return the process-cached device form factor, or ``unknown``."""
    return _detect_chassis_type()
