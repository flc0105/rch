import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from uuid import uuid4

from core.client_revision import CLIENT_BUNDLE_SOURCE_PATHS, build_client_revision_manifest
from core.utils.logger import logger
from core.platform.normalization import normalize_arch


class AgentBuilder:

    EXCLUDE_DIRS = {'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', '.idea', '.vscode' } #'runtime'
    EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.pyd'}
    EXCLUDE_FILE_PATTERNS = {'nohup.out', 'nohup.out.*'}
    BUNDLE_INCLUDE_PATHS = CLIENT_BUNDLE_SOURCE_PATHS
    PYINSTALLER_INCLUDE_PATHS = BUNDLE_INCLUDE_PATHS
    GO_INCLUDE_PATHS = ('client-go',)
    GO_LOADER_INCLUDE_PATHS = ('go-loader',)
    SUPPORTED_TARGETS = {'win', 'mac', 'linux'}
    SUPPORTED_BUILDERS = {'pyinstaller', 'go', 'go_loader', 'bundle'}
    SUPPORTED_GO_ARCHES = {'amd64', 'arm64'}
    BUILD_STATUS_MESSAGE = 'Build completed.'
    PYINSTALLER_PLATFORM_MAP = {
        'Windows': 'win',
        'Darwin': 'mac',
        'Linux': 'linux',
    }
    GO_TARGET_MAP = {
        'win': {'GOOS': 'windows', 'suffix': '.exe', 'label': 'windows'},
        'mac': {'GOOS': 'darwin', 'suffix': '', 'label': 'mac'},
        'linux': {'GOOS': 'linux', 'suffix': '', 'label': 'linux'},
    }

    def __init__(self):
        self.source_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        self.output_dir = os.path.join(self.source_dir, 'runtime', 'agent_output')
        self._ensure_dirs()

    def _ensure_dirs(self):
        os.makedirs(self.output_dir, exist_ok=True)

    def _build_id_text(self) -> str:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        return f'{stamp}-{uuid4().hex[:8]}'

    def _build_kind_text(self, builder: str) -> str:
        builder_name = (builder or '').strip().lower()

        if builder_name == 'bundle':
            return 'source-bundle'
        if builder_name == 'go':
            return 'go-client'
        if builder_name == 'go_loader':
            return 'go-loader'
        if builder_name == 'pyinstaller':
            return 'pyinstaller'

        return builder_name or 'build'

    def _build_version_text(self, builder: str, build_id: str) -> str:
        return f'{self._build_kind_text(builder)}-{build_id}'

    def _build_pyinstaller_output_name(self, target_os: str, build_id: str) -> str:
        suffix = '.exe' if target_os == 'win' else ''
        return f'rchclient-pyinstaller-{target_os}-{build_id}{suffix}'

    def _build_go_output_name(self, target_os: str, normalized_arch: str, build_id: str) -> str:
        suffix = self.GO_TARGET_MAP[target_os]['suffix']
        return f'rchclient-go-client-{target_os}-{normalized_arch}-{build_id}{suffix}'

    def _build_go_loader_output_name(self, target_os: str, normalized_arch: str, build_id: str) -> str:
        suffix = self.GO_TARGET_MAP[target_os]['suffix']
        return f'rchclient-go-loader-{target_os}-{normalized_arch}-{build_id}{suffix}'

    def _build_bundle_output_name(self, build_id: str) -> str:
        return f'rchclient-source-bundle-{build_id}.zip'

    def build_agent(self, server_host: str, server_port: int,
                    web_port: int, file_transfer_port: int, target_os: str = 'mac',
                    builder: str = 'pyinstaller', target_arch: str = '',
                    server_web_scheme: str = 'http', server_web_host: str = '') -> dict:
        builder = (builder or 'pyinstaller').strip().lower()
        target_arch = self._normalize_goarch(target_arch)
        target_os = (target_os or 'mac').strip().lower()
        server_web_scheme = (server_web_scheme or 'http').strip().lower() or 'http'
        server_web_host = (server_web_host or server_host).strip() or server_host

        if builder not in self.SUPPORTED_BUILDERS:
            raise ValueError(f'Unsupported builder: {builder}')
        if builder in {'go', 'go_loader'} and target_arch not in self.SUPPORTED_GO_ARCHES:
            raise ValueError(f'Unsupported target arch: {target_arch or "empty"}')
        if builder != 'bundle' and target_os not in self.SUPPORTED_TARGETS:
            raise ValueError(f'Unsupported target OS: {target_os}')

        work_dir = tempfile.mkdtemp(prefix='agent_build_')
        build_id = self._build_id_text()
        build_version = self._build_version_text(builder, build_id)

        try:
            if builder == 'pyinstaller':
                result = self._build_with_pyinstaller(
                    work_dir=work_dir,
                    server_host=server_host,
                    server_port=server_port,
                    web_port=web_port,
                    file_transfer_port=file_transfer_port,
                    target_os=target_os,
                    build_id=build_id,
                    build_version=build_version,
                    server_web_scheme=server_web_scheme,
                    server_web_host=server_web_host,
                )
            elif builder == 'bundle':
                result = self._build_with_bundle(
                    work_dir=work_dir,
                    server_host=server_host,
                    server_port=server_port,
                    web_port=web_port,
                    file_transfer_port=file_transfer_port,
                    build_id=build_id,
                    build_version=build_version,
                    server_web_scheme=server_web_scheme,
                    server_web_host=server_web_host,
                )
            elif builder == 'go_loader':
                result = self._build_with_go_loader(
                    work_dir=work_dir,
                    server_host=server_host,
                    server_port=server_port,
                    web_port=web_port,
                    file_transfer_port=file_transfer_port,
                    target_os=target_os,
                    target_arch=target_arch,
                    build_id=build_id,
                    build_version=build_version,
                    server_web_scheme=server_web_scheme,
                    server_web_host=server_web_host,
                )
            else:
                result = self._build_with_go(
                    work_dir=work_dir,
                    server_host=server_host,
                    server_port=server_port,
                    web_port=web_port,
                    file_transfer_port=file_transfer_port,
                    target_os=target_os,
                    target_arch=target_arch,
                    build_id=build_id,
                    build_version=build_version,
                    server_web_scheme=server_web_scheme,
                    server_web_host=server_web_host,
                )

            output_path = os.path.join(self.output_dir, result['file_name'])
            shutil.copy2(result['file_path'], output_path)

            warnings = result.get('warnings', [])
            if not isinstance(warnings, list):
                warnings = [str(warnings)]

            return {
                'file_path': output_path,
                'file_name': result['file_name'],
                'size': os.path.getsize(output_path),
                'builder': builder,
                'target_os': result.get('target_os', target_os),
                'warnings': warnings,
                'target_arch': result.get('target_arch', target_arch or 'n/a'),
                'build_version': build_version,
            }
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _copy_source_paths(self, relative_paths, dst: str):
        os.makedirs(dst, exist_ok=True)
        ignore = shutil.ignore_patterns(
            *self.EXCLUDE_DIRS,
            *[f'*{ext}' for ext in self.EXCLUDE_EXTENSIONS],
            *self.EXCLUDE_FILE_PATTERNS,
        )
        for relative_path in relative_paths:
            source_path = os.path.join(self.source_dir, relative_path)
            if not os.path.exists(source_path):
                raise FileNotFoundError(f'Build source not found: {relative_path}')
            target_path = os.path.join(dst, relative_path)
            if os.path.isdir(source_path):
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copytree(
                    source_path,
                    target_path,
                    ignore=ignore,
                    ignore_dangling_symlinks=True,
                )
            else:
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(source_path, target_path)

    def _inject_config(self, client_dir: str, server_host: str, server_port: int, web_port: int,
                       file_transfer_port: int,
                       build_version: str, server_web_scheme: str = 'http', server_web_host: str = ''):
        config_path = os.path.join(client_dir, 'client', 'config', 'config.py')
        server_web_host = (server_web_host or server_host).strip() or server_host
        revision_manifest = build_client_revision_manifest(self.source_dir)
        client_revision = str(revision_manifest.get('revision') or '')
        client_revision_parts = json.dumps(revision_manifest.get('parts') or {}, ensure_ascii=False, sort_keys=True)
        client_revision_files = json.dumps(revision_manifest.get('files') or {}, ensure_ascii=False, sort_keys=True)
        template = f'''import os

SERVER_HOST = "{server_host}"
SERVER_PORT = {server_port}
SERVER_ADDR = (SERVER_HOST, SERVER_PORT)

SERVER_WEB_SCHEME = "{server_web_scheme}"
SERVER_WEB_HOST = "{server_web_host}"
SERVER_WEB_PORT = {web_port}
SERVER_FILE_TRANSFER_PORT = {file_transfer_port}
UPLOAD_BASE_URL = f"{{SERVER_WEB_SCHEME}}://{{SERVER_WEB_HOST}}:{{SERVER_WEB_PORT}}"
FILE_TRANSFER_BASE_URL = f"{{SERVER_WEB_SCHEME}}://{{SERVER_WEB_HOST}}:{{SERVER_FILE_TRANSFER_PORT}}"

CLIENT_BUILD_VERSION = "{build_version}"
RUNTIME_CONFIG = {{
    'server_host': SERVER_HOST,
    'server_port': SERVER_PORT,
    'server_web_scheme': SERVER_WEB_SCHEME,
    'server_web_host': SERVER_WEB_HOST,
    'server_web_port': SERVER_WEB_PORT,
    'server_file_transfer_port': SERVER_FILE_TRANSFER_PORT,
    'client_build_version': CLIENT_BUILD_VERSION,
}}
CLIENT_SOURCE_REVISION = "{client_revision}"
CLIENT_SOURCE_REVISION_PARTS = {client_revision_parts}
CLIENT_SOURCE_REVISION_FILES = {client_revision_files}
'''
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(template)

    def _inject_go_config(self, client_dir: str, server_host: str, server_port: int, web_port: int,
                          file_transfer_port: int,
                          build_version: str, server_web_scheme: str = 'http', server_web_host: str = ''):
        config_path = os.path.join(client_dir, 'client-go', 'config', 'config.go')
        server_web_host = (server_web_host or server_host).strip() or server_host
        template = f'''package config

var SERVER_ADDR = "{server_host}:{server_port}"
var SERVER_WEB_SCHEME = "{server_web_scheme}"
var SERVER_WEB_HOST = "{server_web_host}"
var SERVER_WEB_PORT = {web_port}
var SERVER_FILE_TRANSFER_PORT = {file_transfer_port}
var UPLOAD_BASE_URL = SERVER_WEB_SCHEME + "://" + SERVER_WEB_HOST + ":" + "{web_port}"
var FILE_TRANSFER_BASE_URL = SERVER_WEB_SCHEME + "://" + SERVER_WEB_HOST + ":" + "{file_transfer_port}"
var CLIENT_BUILD_VERSION = "{build_version}"
'''
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(template)

    def _inject_go_loader_config(self, client_dir: str, server_host: str, server_port: int, web_port: int,
                                 file_transfer_port: int,
                                 build_version: str, server_web_scheme: str = 'http', server_web_host: str = ''):
        config_path = os.path.join(client_dir, 'go-loader', 'config', 'config.go')
        server_web_host = (server_web_host or server_host).strip() or server_host
        template = f'''package config

const ServerSocketHost = "{server_host}"
const ServerSocketPort = {server_port}
const ServerWebScheme = "{server_web_scheme}"
const ServerWebHost = "{server_web_host}"
const ServerWebPort = {web_port}
const ServerFileTransferPort = {file_transfer_port}
const LoaderBuildVersion = "{build_version}"
const BundleBaseDirName = "client_bundle"
const BundleBuildAPIPath = "/api/agent/build"
const BundleReportAPIPath = "/api/agent/loader/report"
'''
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(template)

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
        self._copy_source_paths(self.PYINSTALLER_INCLUDE_PATHS, client_copy)
        logger.info(f'Temporary workspace: {os.path.abspath(client_copy)}')
        self._inject_config(
            client_copy,
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

    def _build_with_go(self, work_dir: str, server_host: str, server_port: int,
                       web_port: int, file_transfer_port: int, target_os: str, target_arch: str,
                       build_id: str = '', build_version: str = 'dev', server_web_scheme: str = 'http',
                       server_web_host: str = '') -> dict:
        go_project_dir = os.path.join(self.source_dir, 'client-go')
        if not os.path.isdir(go_project_dir):
            raise FileNotFoundError('client-go directory not found')

        client_copy = os.path.join(work_dir, 'rat')
        self._copy_source_paths(self.GO_INCLUDE_PATHS, client_copy)
        logger.info(f'Temporary workspace: {os.path.abspath(client_copy)}')
        self._inject_go_config(
            client_copy,
            server_host,
            server_port,
            web_port,
            file_transfer_port,
            build_version,
            server_web_scheme,
            server_web_host,
        )

        go_target = self.GO_TARGET_MAP[target_os]
        output_name = self._build_go_output_name(target_os, target_arch, build_id)
        output_path = os.path.join(client_copy, 'client-go', output_name)
        self._run_go_build(os.path.join(client_copy, 'client-go'), output_path, go_target['GOOS'], target_arch)

        return {
            'file_path': output_path,
            'file_name': output_name,
            'warnings': [self.BUILD_STATUS_MESSAGE],
            'target_arch': target_arch,
            'target_os': target_os,
        }

    def _build_with_go_loader(self, work_dir: str, server_host: str, server_port: int,
                              web_port: int, file_transfer_port: int, target_os: str, target_arch: str,
                              build_id: str = '', build_version: str = 'dev', server_web_scheme: str = 'http',
                              server_web_host: str = '') -> dict:
        go_project_dir = os.path.join(self.source_dir, 'go-loader')
        if not os.path.isdir(go_project_dir):
            raise FileNotFoundError('go-loader directory not found')

        client_copy = os.path.join(work_dir, 'rat')
        self._copy_source_paths(self.GO_LOADER_INCLUDE_PATHS, client_copy)
        logger.info(f'Temporary workspace: {os.path.abspath(client_copy)}')
        self._inject_go_loader_config(
            client_copy,
            server_host,
            server_port,
            web_port,
            file_transfer_port,
            build_version,
            server_web_scheme,
            server_web_host,
        )

        go_target = self.GO_TARGET_MAP[target_os]
        output_name = self._build_go_loader_output_name(target_os, target_arch, build_id)
        output_path = os.path.join(client_copy, 'go-loader', output_name)
        self._run_go_build(os.path.join(client_copy, 'go-loader'), output_path, go_target['GOOS'], target_arch)

        return {
            'file_path': output_path,
            'file_name': output_name,
            'warnings': [self.BUILD_STATUS_MESSAGE],
            'target_arch': target_arch,
            'target_os': target_os,
        }

    def _run_go_build(self, cwd: str, output_path: str, goos: str, goarch: str):
        env = os.environ.copy()
        env.update({'CGO_ENABLED': '0', 'GOOS': goos, 'GOARCH': goarch})
        cmd = ['go', 'build', '-trimpath', '-ldflags', '-s -w', '-o', output_path, '.']
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise RuntimeError(f'Go build failed: {result.stderr or result.stdout}')
        if not os.path.exists(output_path):
            raise RuntimeError(f'Build output not found: {output_path}')
        if goos != 'windows':
            os.chmod(output_path, 0o755)

    def _build_with_bundle(self, work_dir: str, server_host: str, server_port: int,
                           web_port: int, file_transfer_port: int, build_id: str, build_version: str,
                           server_web_scheme: str = 'http', server_web_host: str = '') -> dict:
        staging_dir = os.path.join(work_dir, 'bundle')
        self._copy_source_paths(self.BUNDLE_INCLUDE_PATHS, staging_dir)

        self._inject_config(
            staging_dir,
            server_host,
            server_port,
            web_port,
            file_transfer_port,
            build_version,
            server_web_scheme,
            server_web_host,
        )
        bundle_name = self._build_bundle_output_name(build_id)
        bundle_path = os.path.join(work_dir, bundle_name)

        with zipfile.ZipFile(bundle_path, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
            for relative_path in self.BUNDLE_INCLUDE_PATHS:
                source_path = os.path.join(staging_dir, relative_path)
                if os.path.isdir(source_path):
                    for root, _, files in os.walk(source_path):
                        for filename in files:
                            file_path = os.path.join(root, filename)
                            arcname = os.path.relpath(file_path, staging_dir)
                            archive.write(file_path, arcname=arcname)
                else:
                    archive.write(source_path, arcname=relative_path)

        return {
            'file_path': bundle_path,
            'file_name': bundle_name,
            'warnings': [self.BUILD_STATUS_MESSAGE],
            'target_arch': 'n/a',
            'target_os': 'bundle',
        }

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

    def _normalize_goarch(self, arch: str) -> str:
        return normalize_arch(arch)

    def _describe_target(self, target_os: str) -> str:
        mapping = {'win': 'Windows', 'mac': 'macOS', 'linux': 'Linux', 'bundle': 'Bundle'}
        return mapping.get(target_os, target_os)
