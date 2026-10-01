import os
import platform

from client.config.config import (
    CLIENT_BUILD_VERSION,
    CLIENT_SOURCE_REVISION,
    CLIENT_SOURCE_REVISION_PARTS,
    CLIENT_SOURCE_REVISION_FILES,
)
from client.config.runtime_config import (
    HTTP_TRANSFER_MODE,
    LOCAL_WATCHDOG_ENABLED,
    PYTHON_EXECUTION_MODE,
    REMOTE_HTTP_WATCHDOG_ENABLED,
)
from core.client_revision import build_client_revision_manifest
from core.device.local_identity import get_local_identity
from client.runtime.client_util import check_privilege, get_executable_path, get_system_paths


_CLIENT_REVISION_MANIFEST = None


def _get_client_revision_manifest() -> dict:
    global _CLIENT_REVISION_MANIFEST

    if CLIENT_SOURCE_REVISION:
        return {
            'revision': str(CLIENT_SOURCE_REVISION),
            'parts': dict(CLIENT_SOURCE_REVISION_PARTS or {}),
            'files': dict(CLIENT_SOURCE_REVISION_FILES or {}),
        }

    if _CLIENT_REVISION_MANIFEST is None:
        _CLIENT_REVISION_MANIFEST = build_client_revision_manifest()

    return dict(_CLIENT_REVISION_MANIFEST)


class ClientInfoBuilder:
    """
    构造客户端握手信息。
    """

    def __init__(self, client_id, command_executor=None):
        self.client_id = client_id
        self.command_executor = command_executor

    def build(self):
        """
        构造客户端基础信息
        """
        identity = get_local_identity()
        process_info = self._build_process_info(identity.os_alias)
        revision_manifest = _get_client_revision_manifest()

        info = {
            'id': self.client_id,
            'type': 'info',

            'os_type': identity.os_type,
            'os_alias': identity.os_alias,
            'os_full': identity.os_full,
            'os_name': identity.os_name,
            'os_ver': identity.os_version,

            'arch': identity.arch,
            'manufacturer': identity.manufacturer,
            'model': identity.model,

            'hostname': identity.hostname,
            'machine_id': identity.machine_id,
            'machine_fingerprint_basis': identity.fingerprint_basis,
            'build_version': CLIENT_BUILD_VERSION,
            'client_revision': revision_manifest.get('revision') or '',
            'client_revision_parts': dict(revision_manifest.get('parts') or {}),
            'client_revision_files': dict(revision_manifest.get('files') or {}),

            'process_id': os.getpid(),
            'launch_command': get_executable_path(),
            'username': process_info['username'],
            'process_name': process_info['process_name'],
            'integrity': check_privilege(),
            'cwd': os.getcwd(),
            'python_ver': platform.python_version(),

            'http_transfer_mode': HTTP_TRANSFER_MODE,
            'python_execution_mode': PYTHON_EXECUTION_MODE,
            'remote_watchdog_enabled': REMOTE_HTTP_WATCHDOG_ENABLED,
            'local_watchdog_enabled': LOCAL_WATCHDOG_ENABLED,

            'command_manifest': self._build_command_manifest(),
            'variable_manifest': self._build_variable_manifest(),
            'system_paths': get_system_paths(),
        }
        return info

    def _build_command_manifest(self):
        command_manifest = []
        try:
            if self.command_executor is not None:
                commands = self.command_executor.get_commands()
                if hasattr(commands, 'get_command_manifest_payload'):
                    command_manifest = commands.get_command_manifest_payload()
        except Exception:
            command_manifest = []
        return command_manifest

    def _build_variable_manifest(self):
        variable_manifest = []
        try:
            if self.command_executor is not None:
                getter = getattr(self.command_executor, 'get_command_variable_manifest', None)
                if callable(getter):
                    variable_manifest = getter()
        except Exception:
            variable_manifest = []
        return variable_manifest

    def _build_process_info(self, os_alias: str):
        try:
            if os_alias == 'ios':
                from client.commands.platform.utils.ios_util import get_ios_process_info

                ios_process_info = get_ios_process_info()
                username = ios_process_info.get('username')
                process_name = ios_process_info.get('process_name')
                # 记录process_uptime和system_uptime是没用的，因为这条消息是一次性传输的握手信息，并不会实时更新，容易产生误导。
                # 如果要获取uptime相关信息请用getinfo命令
            else:
                import psutil
                process = psutil.Process()
                username = process.username()
                process_name = process.name()
        except Exception:
            username = ""
            process_name = ""

        return {
            'username': username,
            'process_name': process_name,
        }