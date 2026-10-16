"""Optional PyInstaller builder. Remove this file and its registry entry to disable it."""
import os
import platform
import subprocess
from core.client_revision import CLIENT_BUNDLE_SOURCE_PATHS
from server.application.agent.agent_build_utils import copy_source_paths, inject_python_client_config
from core.utils.logger import logger


class PyInstallerBuilder:
    PYINSTALLER_INCLUDE_PATHS = CLIENT_BUNDLE_SOURCE_PATHS
    BUILD_STATUS_MESSAGE = 'Build completed.'
    PYINSTALLER_PLATFORM_MAP = {
        'Windows': 'win',
        'Darwin': 'mac',
        'Linux': 'linux',
    }

    def __init__(self, source_dir: str):
        self.source_dir = source_dir

    def _build_pyinstaller_output_name(self, target_os: str, build_id: str) -> str:
        suffix = '.exe' if target_os == 'win' else ''
        return f'rchclient-pyinstaller-{target_os}-{build_id}{suffix}'

    def _build_with_pyinstaller(self, work_dir: str, server_host: str, server_port: int,
                                web_port: int, file_transfer_port: int, target_os: str,
                                build_id: str = '', build_version: str = 'dev', server_web_scheme: str = 'http',
                                server_web_host: str = '') -> dict:
        current_target = self._get_current_pyinstaller_target()
        if current_target != target_os:
            current_label = self._describe_target(current_target)
            raise ValueError(
                'PyInstaller only supports building for the same platform as the current server. '
                f'Current server platform: {current_label}.'
            )

        client_copy = os.path.join(work_dir, 'rat')
        copy_source_paths(self.source_dir, self.PYINSTALLER_INCLUDE_PATHS, client_copy)
        logger.info(f'Temporary workspace: {os.path.abspath(client_copy)}')
        inject_python_client_config(
            self.source_dir, client_copy,
            server_host,
            server_port,
            web_port,
            file_transfer_port,
            build_version,
            server_web_scheme,
            server_web_host,
        )

        if target_os == 'win':
            result = self._build_windows(client_copy, build_id=build_id, build_version=build_version)
        elif target_os == 'linux':
            result = self._build_linux(client_copy, build_id=build_id, build_version=build_version)
        else:
            result = self._build_macos(client_copy, build_id=build_id, build_version=build_version)

        result['warnings'] = [self.BUILD_STATUS_MESSAGE]
        result['target_arch'] = 'n/a'
        result['target_os'] = target_os
        return result

    def _build_macos(self, client_dir: str, build_id: str = '', build_version: str = 'dev') -> dict:
        cmd = ['pyinstaller', '-F', '-w', 'rchclient.py',
               '--hidden-import', 'client.commands.platform.mac',
               '--hidden-import', 'client.commands.platform.win',
               '--hidden-import', 'client.commands.platform.linux']
        result = subprocess.run(cmd, cwd=client_dir, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'PyInstaller failed: {result.stderr}')
        exe_path = os.path.join(client_dir, 'dist', 'rchclient')
        if not os.path.exists(exe_path):
            raise RuntimeError(f'Build output not found: {exe_path}')
        os.chmod(exe_path, 0o755)
        return {'file_path': exe_path, 'file_name': self._build_pyinstaller_output_name('mac', build_id)}

    def _build_windows(self, client_dir: str, build_id: str = '', build_version: str = 'dev') -> dict:
        cmd = ['pyinstaller', '-F', '-w', 'rchclient.py',
               '--hidden-import', 'client.commands.platform.mac',
               '--hidden-import', 'client.commands.platform.win',
               '--hidden-import', 'client.commands.platform.linux']
        result = subprocess.run(cmd, cwd=client_dir, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            raise RuntimeError(f'PyInstaller failed: {result.stderr}')
        exe_path = os.path.join(client_dir, 'dist', 'rchclient.exe')
        if not os.path.exists(exe_path):
            raise RuntimeError(f'Build output not found: {exe_path}')
        return {'file_path': exe_path, 'file_name': self._build_pyinstaller_output_name('win', build_id)}

    def _build_linux(self, client_dir: str, build_id: str = '', build_version: str = 'dev') -> dict:
        cmd = ['pyinstaller', '-F', '-w', 'rchclient.py',
               '--hidden-import', 'client.commands.platform.mac',
               '--hidden-import', 'client.commands.platform.win',
               '--hidden-import', 'client.commands.platform.linux']
        result = subprocess.run(cmd, cwd=client_dir, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'PyInstaller failed: {result.stderr}')
        exe_path = os.path.join(client_dir, 'dist', 'rchclient')
        if not os.path.exists(exe_path):
            raise RuntimeError(f'Build output not found: {exe_path}')
        os.chmod(exe_path, 0o755)
        return {'file_path': exe_path, 'file_name': self._build_pyinstaller_output_name('linux', build_id)}

    def _get_current_pyinstaller_target(self) -> str:
        current_system = platform.system()
        current_target = self.PYINSTALLER_PLATFORM_MAP.get(current_system)
        if not current_target:
            raise ValueError(f'The current server platform does not support PyInstaller: {current_system}')
        return current_target

    def _describe_target(self, target_os: str) -> str:
        mapping = {'win': 'Windows', 'mac': 'macOS', 'linux': 'Linux', 'bundle': 'Bundle'}
        return mapping.get(target_os, target_os)


    def build(self, *, target_arch: str, **kwargs):
        return self._build_with_pyinstaller(**kwargs)
