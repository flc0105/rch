"""Optional Go Loader builder; independently removable from Client-Go."""
import os
from core.utils.logger import logger
from server.application.agent.agent_go_build_runner import GO_TARGET_MAP as SHARED_GO_TARGET_MAP, run_go_build
from server.application.agent.agent_build_utils import copy_source_paths


class GoLoaderBuilder:
    GO_LOADER_INCLUDE_PATHS = ('go-loader',)
    GO_TARGET_MAP = SHARED_GO_TARGET_MAP
    BUILD_STATUS_MESSAGE = 'Build completed.'

    def __init__(self, source_dir: str):
        self.source_dir = source_dir

    def _build_go_loader_output_name(self, target_os: str, normalized_arch: str, build_id: str) -> str:
        suffix = self.GO_TARGET_MAP[target_os]['suffix']
        return f'rchclient-go-loader-{target_os}-{normalized_arch}-{build_id}{suffix}'

    def _inject_go_loader_config(self, client_dir: str, server_host: str, server_port: int, web_port: int,
                                 build_version: str, server_web_scheme: str = 'http', server_web_host: str = '',
                                 listener_id: str = ''):
        config_path = os.path.join(client_dir, 'go-loader', 'config', 'config.go')
        server_web_host = (server_web_host or server_host).strip() or server_host
        template = f'''package config

const ServerSocketHost = "{server_host}"
const ServerSocketPort = {server_port}
const ServerListenerID = "{listener_id}"
const ServerWebScheme = "{server_web_scheme}"
const ServerWebHost = "{server_web_host}"
const ServerWebPort = {web_port}
const LoaderBuildVersion = "{build_version}"
const BundleBaseDirName = "client_bundle"
const BundleBuildAPIPath = "/api/agent/build"
const BundleReportAPIPath = "/api/agent/loader/report"
'''
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(template)

    def _build_with_go_loader(self, work_dir: str, server_host: str, server_port: int,
                              web_port: int, target_os: str, target_arch: str,
                              build_id: str = '', build_version: str = 'dev', server_web_scheme: str = 'http',
                              server_web_host: str = '', listener_id: str = '') -> dict:
        go_project_dir = os.path.join(self.source_dir, 'go-loader')
        if not os.path.isdir(go_project_dir):
            raise FileNotFoundError('go-loader directory not found')

        client_copy = os.path.join(work_dir, 'rat')
        copy_source_paths(self.source_dir, self.GO_LOADER_INCLUDE_PATHS, client_copy)
        logger.info(f'Temporary workspace: {os.path.abspath(client_copy)}')
        self._inject_go_loader_config(
            client_copy,
            server_host,
            server_port,
            web_port,
            build_version,
            server_web_scheme,
            server_web_host,
            listener_id,
        )

        go_target = self.GO_TARGET_MAP[target_os]
        output_name = self._build_go_loader_output_name(target_os, target_arch, build_id)
        output_path = os.path.join(client_copy, 'go-loader', output_name)
        run_go_build(os.path.join(client_copy, 'go-loader'), output_path, go_target['GOOS'], target_arch)

        return {
            'file_path': output_path,
            'file_name': output_name,
            'warnings': [self.BUILD_STATUS_MESSAGE],
            'target_arch': target_arch,
            'target_os': target_os,
        }

    def build(self, **kwargs):
        target_os = kwargs.get('target_os', '')
        if target_os not in self.GO_TARGET_MAP:
            raise ValueError(f'Unsupported target OS: {target_os}')
        target_arch = kwargs.get('target_arch', '')
        if target_arch not in {'amd64', 'arm64'}:
            raise ValueError(f'Unsupported target arch: {target_arch or "empty"}')
        return self._build_with_go_loader(**kwargs)
