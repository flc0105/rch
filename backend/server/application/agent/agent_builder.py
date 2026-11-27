import importlib
import importlib.util
import os
import shutil
import tempfile
from datetime import datetime
from uuid import uuid4

from core.platform.normalization import normalize_arch
from core.agent_build_contract import AgentBuilderKind, agent_build_version
from server.config.config import SERVER_RUNTIME_DIR
from server.runtime.listener_protocols import get_listener_protocol


# Single registration point. Remove an entry to disable a builder without deleting its file.
# All builders are peers; even Bundle may be unregistered. Restart after editing this map.
AGENT_BUILDERS = {
    AgentBuilderKind.PYTHON.value: ('server.application.agent.agent_build_bundle', 'BundleBuilder'),
    AgentBuilderKind.GO.value: ('server.application.agent.agent_build_client_go', 'ClientGoBuilder'),
    AgentBuilderKind.GO_LOADER.value: ('server.application.agent.agent_build_go_loader', 'GoLoaderBuilder'),
    # Optional PyInstaller remains available as a source module; not registered by default.
    # 'pyinstaller': ('server.application.agent.agent_build_pyinstaller', 'PyInstallerBuilder'),
}


class AgentBuilder:

    def __init__(self):
        self.source_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        self.output_dir = os.path.join(SERVER_RUNTIME_DIR, 'agent_output')
        self.work_root = os.path.join(SERVER_RUNTIME_DIR, 'agent_build_tmp')
        self._ensure_dirs()

    @property
    def SUPPORTED_BUILDERS(self) -> set[str]:
        return {name for name, (module_name, _) in AGENT_BUILDERS.items()
                if importlib.util.find_spec(module_name) is not None}

    def list_supported_builders(self) -> list[str]:
        """Expose only registered, installed builders (possibly none)."""
        supported = self.SUPPORTED_BUILDERS
        return [name for name in AGENT_BUILDERS if name in supported]

    def _ensure_dirs(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.work_root, mode=0o700, exist_ok=True)

    def _build_id_text(self) -> str:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f'{stamp}_{uuid4().hex[:8]}'

    def _build_version_text(self, builder: str, build_id: str) -> str:
        return agent_build_version(builder, build_id)

    def build_agent(self, server_host: str, server_port: int,
                    web_port: int, target_os: str = 'mac',
                    builder: str = '', target_arch: str = '',
                    server_web_scheme: str = 'http', server_web_host: str = '',
                    listener_protocol: str = 'tcp',
                    listener_id: str = '', connection_mode: str = 'reverse',
                    bind_host: str = '0.0.0.0', bind_port: int = 9443) -> dict:
        builder = (builder or '').strip().lower()
        if not builder:
            raise ValueError('builder is required')
        target_arch = self._normalize_goarch(target_arch)
        target_os = (target_os or 'mac').strip().lower()
        server_web_scheme = (server_web_scheme or 'http').strip().lower() or 'http'
        server_web_host = (server_web_host or server_host).strip() or server_host

        connection_mode = str(connection_mode or 'reverse').strip().lower()
        if connection_mode not in ('reverse', 'bind'):
            raise ValueError('connection_mode must be reverse or bind')
        if connection_mode == 'bind':
            if not isinstance(bind_host, str) or not bind_host.strip():
                raise ValueError('bind_host is required')
            bind_host = bind_host.strip()
            if type(bind_port) is not int or not 1 <= bind_port <= 65535:
                raise ValueError('bind_port must be between 1 and 65535')
            if listener_protocol not in ('tcp', 'mtls_tcp'):
                raise ValueError('Bind mode requires TCP or mTLS')
        else:
            get_listener_protocol(listener_protocol).validate_build(builder)

        if builder not in self.SUPPORTED_BUILDERS:
            raise ValueError(f'Unsupported builder: {builder}')

        if not 1 <= int(web_port) <= 65534:
            raise ValueError('web_port must be between 1 and 65534')

        work_dir = tempfile.mkdtemp(prefix='agent_build_', dir=self.work_root)
        build_id = self._build_id_text()
        build_version = self._build_version_text(builder, build_id)

        try:
            common_args = dict(
                work_dir=work_dir,
                server_host=server_host,
                server_port=server_port,
                web_port=web_port,
                build_id=build_id,
                build_version=build_version,
                server_web_scheme=server_web_scheme,
                server_web_host=server_web_host,
            )
            if builder in (AgentBuilderKind.PYTHON.value, AgentBuilderKind.GO.value, AgentBuilderKind.GO_LOADER.value):
                common_args['listener_protocol'] = listener_protocol
                common_args.update(connection_mode=connection_mode, bind_host=bind_host, bind_port=bind_port)
            if builder == AgentBuilderKind.GO_LOADER.value:
                common_args['listener_id'] = listener_id
            module_name, class_name = AGENT_BUILDERS[builder]
            build_module = importlib.import_module(module_name)
            builder_class = getattr(build_module, class_name)
            result = builder_class(self.source_dir).build(
                target_os=target_os, target_arch=target_arch, **common_args,
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

    def _normalize_goarch(self, arch: str) -> str:
        return normalize_arch(arch)
