import json
import os
import platform
import sys
import time
from datetime import datetime

from client.commands.platform.utils.ios_util import (
    _safe_call,
    get_icloud_path,
    get_ios_bundle_info,
    get_ios_device_info,
    get_ios_process_info,
    get_ios_username,
    read_info_plist,
)
from client.runtime.client_util import get_executable_path
from core.utils.command_output import StructuredCommandResult
from core.utils.logger import logger


class iOSSystemService:
    """
    iOS / Pythonista 系统信息能力。
    """

    def __init__(self, owner):
        self.owner = owner

    def get_username(self):
        try:
            return 1, str(get_ios_username())
        except Exception as e:
            return 0, f'whoami failed: {e}'

    def collect_info(self):
        try:
            from pathlib import Path

            device = get_ios_device_info()
            proc = get_ios_process_info()
            bundle = get_ios_bundle_info()

            info = {
                'device_name': device.get('device_name'),
                'device_model': device.get('device_model'),
                'device_type': device.get('device_type'),
                'machine_name': device.get('machine_name') or platform.machine(),
                'hostname': device.get('hostname'),
                'system': device.get('system'),
                'system_version': device.get('system_version'),
                'identifier_for_vendor': device.get('identifier_for_vendor'),
                'platform': _safe_call(platform.platform),
                'kernel_release': _safe_call(platform.release),
                'kernel_version': _safe_call(platform.version),
                'python_compiler': _safe_call(platform.python_compiler),
                'python_version': sys.version,
                'python_version_short': _safe_call(platform.python_version),
                'process_name': proc.get('process_name'),
                'process_id': proc.get('process_id'),
                'username': proc.get('username'),
                'executable_path': get_executable_path(),
                'processor_count': proc.get('processor_count'),
                'physical_memory': proc.get('physical_memory'),
                'system_boot_time': proc.get('system_boot_time'),
                'system_uptime': proc.get('system_uptime'),
                'os_version_string': proc.get('operating_system_version_string'),
                'low_power_mode_enabled': proc.get('low_power_mode_enabled'),
                'bundle_identifier': bundle.get('bundle_identifier'),
                'bundle_path': bundle.get('bundle_path'),
                'bundle_executable_path': bundle.get('executable_path') or sys.executable,
                'bundle_name': bundle.get('bundle_name'),
                'app_name': bundle.get('app_name'),
                'bundle_version': bundle.get('bundle_version'),
                'bundle_short_version': bundle.get('bundle_short_version'),
                'cwd': os.getcwd(),
                'home': os.path.expanduser('~') or str(Path.home()),
                'documents': os.path.expanduser('~/Documents'),
                'temp': os.path.abspath(os.getenv('TMPDIR', '/tmp')),
                'icloud': get_icloud_path(read_info_plist())
            }

            return StructuredCommandResult(
                status=1,
                data=info,
                shape='dict',
                width=24,
            )
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0, f'Failed to get system info: {e}'

    def get_uptime(self):
        try:
            from objc_util import ObjCClass

            seconds = max(0, float(ObjCClass('NSProcessInfo').processInfo().systemUptime()))
            boot_time = datetime.fromtimestamp(time.time() - seconds)
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            minutes = int((seconds % 3600) // 60)
            return 1, f"Boot time: {boot_time:%Y-%m-%d %H:%M:%S}\nUptime: {days}d {hours}h {minutes}m"
        except Exception as e:
            return 0, f'Failed to get system uptime: {e}'

    def list_contacts(self):
        try:
            from client.commands.platform.utils.ios_util import get_ios_contacts

            result = get_ios_contacts()
            return StructuredCommandResult(
                status=1,
                data=result,
                shape='table',
            )
        except Exception as e:
            return 0, f'Failed to list contacts: {e}'

    def dump_json(self, payload):
        return json.dumps(payload, ensure_ascii=False)