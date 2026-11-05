import os
import platform
from client.config.config import (
    CLIENT_BUILD_VERSION,
    CLIENT_SOURCE_REVISION,
    CLIENT_SOURCE_REVISION_FILES,
)
from client.config import runtime_config
from core.client_revision import build_client_revision_manifest
from client.runtime.client_logging import get_client_log_path
from core.device.local_identity import get_local_identity
from client.runtime.client_util import check_privilege, get_executable_path, get_system_paths
from client.runtime.launch_context import detect_launch_context


_CLIENT_REVISION_MANIFEST = None
_LAUNCH_CONTEXT = None


def _get_client_revision_manifest() -> dict:
    global _CLIENT_REVISION_MANIFEST

    if CLIENT_SOURCE_REVISION:
        return {
            'revision': str(CLIENT_SOURCE_REVISION),
            'files': dict(CLIENT_SOURCE_REVISION_FILES or {}),
        }

    if _CLIENT_REVISION_MANIFEST is None:
        _CLIENT_REVISION_MANIFEST = build_client_revision_manifest()

    return dict(_CLIENT_REVISION_MANIFEST)


class ClientInfoBuilder:
    """
    构造客户端握手信息。
    """

    def __init__(self, client_id, command_executor=None, features=None):
        self.client_id = client_id
        self.command_executor = command_executor
        self.features = features

    def build(self):
        """
        构造客户端基础信息
        """
        identity = get_local_identity()
        process_info = self._build_process_info(identity.os_alias)
        launch_context = self._get_launch_context(identity.os_alias)
        revision_manifest = _get_client_revision_manifest()

        from client.config.feature_config import resolve_features
        features = dict(self.features if self.features is not None else resolve_features(identity.os_alias))
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
            'client_revision_files': dict(revision_manifest.get('files') or {}),

            'process_id': os.getpid(),
            'launch_command': get_executable_path(),
            'launch_mode': launch_context['mode'],
            'launch_source': launch_context['source'],
            'client_log_path': get_client_log_path(),
            'username': process_info['username'],
            'process_name': process_info['process_name'],
            'integrity': check_privilege(),
            'cwd': os.getcwd(),
            'python_ver': platform.python_version(),

            'http_transfer_mode': runtime_config.HTTP_TRANSFER_MODE,
            'python_execution_mode': runtime_config.PYTHON_EXECUTION_MODE,

            'command_manifest': self._build_command_manifest(),
            'feature_manifest': dict(features),
            'variable_manifest': self._build_variable_manifest(),
            'system_paths': get_system_paths(),
        }
        return info


    @classmethod
    def _get_launch_context(cls, os_alias: str) -> dict:
        global _LAUNCH_CONTEXT
        if _LAUNCH_CONTEXT is None:
            _LAUNCH_CONTEXT = cls._detect_launch_context(os_alias)
        return dict(_LAUNCH_CONTEXT)

    @staticmethod
    def _detect_launch_context(os_alias: str) -> dict:
        return detect_launch_context(os_alias)

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