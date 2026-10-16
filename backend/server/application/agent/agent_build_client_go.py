"""Optional experimental Go Client builder; independently removable."""
import os
import subprocess
from core.utils.logger import logger
from server.application.agent.agent_build_utils import copy_source_paths


class ClientGoBuilder:
    GO_INCLUDE_PATHS = ('client-go',)
    GO_TARGET_MAP = {
        'win': {'GOOS': 'windows', 'suffix': '.exe', 'label': 'windows'},
        'mac': {'GOOS': 'darwin', 'suffix': '', 'label': 'mac'},
        'linux': {'GOOS': 'linux', 'suffix': '', 'label': 'linux'},
    }
    BUILD_STATUS_MESSAGE = 'Build completed.'

    def __init__(self, source_dir: str):
        self.source_dir = source_dir

    def _build_go_output_name(self, target_os: str, normalized_arch: str, build_id: str) -> str:
        suffix = self.GO_TARGET_MAP[target_os]['suffix']
        return f'rchclient-go-client-{target_os}-{normalized_arch}-{build_id}{suffix}'

    def _inject_go_config(self, client_dir: str, server_host: str, server_port: int, web_port: int,
                          file_transfer_port: int,
                          build_version: str, server_web_scheme: str = 'http', server_web_host: str = ''):
        config_path = os.path.join(client_dir, 'client-go', 'config', 'config.go')
        server_web_host = (server_web_host or server_host).strip() or server_host
        template = f'''package config

import "strconv"

var SERVER_ADDR = "{server_host}:{server_port}"
var SERVER_WEB_SCHEME = "{server_web_scheme}"
var SERVER_WEB_HOST = "{server_web_host}"
var SERVER_WEB_PORT = {web_port}
var SERVER_FILE_TRANSFER_PORT = SERVER_WEB_PORT + 1
var UPLOAD_BASE_URL = SERVER_WEB_SCHEME + "://" + SERVER_WEB_HOST + ":" + "{web_port}"
var FILE_TRANSFER_BASE_URL = SERVER_WEB_SCHEME + "://" + SERVER_WEB_HOST + ":" + strconv.Itoa(SERVER_FILE_TRANSFER_PORT)
var CLIENT_BUILD_VERSION = "{build_version}"
'''
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(template)

    def _build_with_go(self, work_dir: str, server_host: str, server_port: int,
                       web_port: int, file_transfer_port: int, target_os: str, target_arch: str,
                       build_id: str = '', build_version: str = 'dev', server_web_scheme: str = 'http',
                       server_web_host: str = '') -> dict:
        go_project_dir = os.path.join(self.source_dir, 'client-go')
        if not os.path.isdir(go_project_dir):
            raise FileNotFoundError('client-go directory not found')

        client_copy = os.path.join(work_dir, 'rat')
        copy_source_paths(self.source_dir, self.GO_INCLUDE_PATHS, client_copy)
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


    def build(self, **kwargs):
        target_os = kwargs.get('target_os', '')
        if target_os not in self.GO_TARGET_MAP:
            raise ValueError(f'Unsupported target OS: {target_os}')
        target_arch = kwargs.get('target_arch', '')
        if target_arch not in {'amd64', 'arm64'}:
            raise ValueError(f'Unsupported target arch: {target_arch or "empty"}')
        return self._build_with_go(**kwargs)
