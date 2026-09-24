import os
import platform
import tempfile
from datetime import datetime

from server.config.config import WEB_FILE_TRANSFER_PORT, WEB_PORT


class WebAgentApi:
    """
    Web Agent 子外观。

    职责：
    - 提供 Agent build 能力
    - 提供构建产物定位能力
    - 提供构建产物列表/删除能力
    - 提供 Go loader 上报落盘能力
    """

    def __init__(self, agent_builder, agent_output_registry, bootstrap_script_service=None, event_bus=None):
        self.agent_builder = agent_builder
        self.agent_output_registry = agent_output_registry
        self.bootstrap_script_service = bootstrap_script_service
        self.event_bus = event_bus
        self.logs_dir = os.path.abspath(os.path.join('runtime', 'logs'))
        os.makedirs(self.logs_dir, exist_ok=True)

    def build_agent(
        self,
        server_host: str,
        server_port: int,
        web_port: int = None,
        file_transfer_port: int = None,
        target_os: str = 'mac',
        builder: str = 'pyinstaller',
        target_arch: str = '',
        server_web_scheme: str = 'http',
        server_web_host: str = '',
        source: str = 'manual',
    ):
        file_transfer_port = int(file_transfer_port or WEB_FILE_TRANSFER_PORT)
        lifecycle_context = {
            'builder': str(builder or '').strip(),
            'target_os': str(target_os or '').strip(),
            'target_arch': str(target_arch or '').strip(),
            'source': str(source or '').strip(),
        }
        try:
            build_result = self.agent_builder.build_agent(
                server_host=server_host,
                server_port=server_port,
                web_port=web_port,
                file_transfer_port=file_transfer_port,
                target_os=target_os,
                builder=builder,
                target_arch=target_arch,
                server_web_scheme=server_web_scheme,
                server_web_host=server_web_host,
            )
            record = self.agent_output_registry.register_output(
                build_result,
                source=source,
                request_payload={
                    'server_host': server_host,
                    'server_port': server_port,
                    'web_port': web_port,
                    'file_transfer_port': file_transfer_port,
                    'target_os': target_os,
                    'builder': builder,
                    'target_arch': target_arch,
                    'server_web_scheme': server_web_scheme,
                    'server_web_host': server_web_host,
                    'source': source,
                },
            )
        except Exception as exc:
            if self.event_bus is not None:
                self.event_bus.publish('agent_build_lifecycle', {
                    **lifecycle_context,
                    'state': 'error',
                    'error': str(exc),
                })
            raise

        record['warnings'] = build_result.get('warnings') or []

        if self.event_bus is not None:
            file_name = str(record.get('file_name') or '').strip()
            self.event_bus.publish('agent_build_lifecycle', {
                **lifecycle_context,
                'state': 'completed',
                'builder': str(record.get('builder') or lifecycle_context['builder']).strip(),
                'target_os': str(record.get('target_os') or lifecycle_context['target_os']).strip(),
                'target_arch': str(record.get('target_arch') or lifecycle_context['target_arch']).strip(),
                'file_name': file_name,
                'download_url': f'/api/agent/download/{file_name}' if file_name else '',
            })

        return record

    def get_built_agent_file_path(self, filename: str):
        file_path = os.path.join(self.agent_builder.output_dir, os.path.basename(filename))
        if not os.path.isfile(file_path):
            raise FileNotFoundError('File not found')
        return file_path

    def list_agent_outputs(self):
        results = []
        for item in self.agent_output_registry.list_outputs():
            copied = dict(item)
            file_name = str(copied.get('file_name') or '').strip()
            copied['download_url'] = f'/api/agent/download/{file_name}' if file_name else ''
            copied['delete_url'] = f'/api/agent/outputs/{file_name}' if file_name else ''
            results.append(copied)
        return results

    def delete_agent_output(self, filename: str):
        return self.agent_output_registry.delete_output(filename)

    def get_server_platform(self):
        system = platform.system()
        target_os = self.agent_builder.PYINSTALLER_PLATFORM_MAP.get(system, 'mac')
        machine = platform.machine().lower()
        if machine in {'arm64', 'aarch64'}:
            target_arch = 'arm64'
        else:
            target_arch = 'amd64'
        return {
            'system': system,
            'target_os': target_os,
            'target_arch': target_arch,
            'web_port': int(WEB_PORT),
            'file_transfer_port': int(WEB_FILE_TRANSFER_PORT),
        }

    def _get_loader_log_path(self) -> str:
        stamp = datetime.now().strftime('%Y%m%d-%H')
        return os.path.join(self.logs_dir, f'go_loader_{stamp}.log')

    def ingest_loader_report(self, payload: dict):
        if not isinstance(payload, dict):
            raise ValueError('Invalid loader payload')

        line = payload.get('line', '')
        if not line or not isinstance(line, str):
            raise ValueError('Missing or invalid line field')

        log_path = self._get_loader_log_path()
        with open(log_path, 'a', encoding='utf-8') as fp:
            fp.write(line.strip() + '\n')

        return {'logged': True, 'log_file': os.path.basename(log_path)}

    def _write_bootstrap_temp_file(self, *, content: str, suffix: str, download_name: str, mimetype: str) -> dict:
        with tempfile.NamedTemporaryFile(
                mode='w', suffix=suffix, delete=False, encoding='utf-8'
        ) as file_obj:
            file_obj.write(content)
            temp_path = file_obj.name

        return {
            'file_path': temp_path,
            'download_name': download_name,
            'mimetype': mimetype,
        }

    def generate_bootstrap_file(self, payload: dict) -> dict:
        if self.bootstrap_script_service is None:
            raise RuntimeError('bootstrap_script_service is not available')

        script_content = self.bootstrap_script_service.generate_python_script(payload)
        return self._write_bootstrap_temp_file(
            content=script_content,
            suffix='.py',
            download_name='bootstrap.py',
            mimetype='text/x-python',
        )

    def generate_bootstrap_ps1_file(self, payload: dict) -> dict:
        if self.bootstrap_script_service is None:
            raise RuntimeError('bootstrap_script_service is not available')

        script_content = self.bootstrap_script_service.generate_powershell_script(payload)
        return self._write_bootstrap_temp_file(
            content=script_content,
            suffix='.ps1',
            download_name='bootstrap.ps1',
            mimetype='text/plain',
        )
