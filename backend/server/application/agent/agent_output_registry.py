from typing import Optional
import json
import os
from datetime import datetime


class AgentOutputRegistry:
    """
    管理 agent_output 目录下的构建产物及其元数据。

    设计：
    - 文件实体保存在 runtime/agent_output
    - 元数据单独保存在 runtime/agent_output/.metadata/<filename>.json
    - 列表展示时以真实文件为准，元数据缺失时自动降级为文件系统信息
    """

    METADATA_DIR_NAME = '.metadata'

    def __init__(self, output_dir: str):
        self.output_dir = os.path.abspath(output_dir)
        self.metadata_dir = os.path.join(self.output_dir, self.METADATA_DIR_NAME)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.metadata_dir, exist_ok=True)

    def _normalize_filename(self, filename: str) -> str:
        name = os.path.basename(str(filename or '').strip())
        if not name or name in {'.', '..'}:
            raise ValueError('Invalid file name')
        return name

    def _metadata_path(self, filename: str) -> str:
        safe_name = self._normalize_filename(filename)
        return os.path.join(self.metadata_dir, f'{safe_name}.json')

    def _safe_join_output(self, filename: str) -> str:
        safe_name = self._normalize_filename(filename)
        file_path = os.path.abspath(os.path.join(self.output_dir, safe_name))
        if os.path.dirname(file_path) != self.output_dir:
            raise ValueError('Invalid file name')
        return file_path

    def _serialize_datetime(self, value) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        text = str(value or '').strip()
        return text

    def _read_metadata(self, filename: str) -> dict:
        metadata_path = self._metadata_path(filename)
        if not os.path.isfile(metadata_path):
            return {}

        try:
            with open(metadata_path, 'r', encoding='utf-8') as fp:
                payload = json.load(fp)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _write_metadata(self, filename: str, payload: dict) -> None:
        metadata_path = self._metadata_path(filename)
        with open(metadata_path, 'w', encoding='utf-8') as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)

    def register_output(self, build_result: dict, *, source: str = 'manual', request_payload: Optional[dict] = None) -> dict:
        payload = dict(request_payload or {})
        file_name = self._normalize_filename(build_result.get('file_name'))
        file_path = self._safe_join_output(file_name)
        stat = os.stat(file_path)
        created_at = datetime.now().isoformat()

        record = {
            'file_name': file_name,
            'build_time': created_at,
            'created_at': created_at,
            'updated_at': created_at,
            'build_version': str(build_result.get('build_version') or '').strip(),
            'builder': str(build_result.get('builder') or payload.get('builder') or '').strip(),
            'source': str(source or payload.get('source') or 'web_manual_build').strip() or 'manual',
            'target_os': str(build_result.get('target_os') or payload.get('target_os') or '').strip(),
            'target_arch': str(build_result.get('target_arch') or payload.get('target_arch') or '').strip(),
            'size': int(build_result.get('size') or stat.st_size or 0),
            'server_host': str(payload.get('server_host') or '').strip(),
            'server_port': int(payload.get('server_port') or 0),
            'web_port': int(payload.get('web_port') or 0),
            'file_transfer_port': int(payload.get('file_transfer_port') or 0),
            'server_web_scheme': str(payload.get('server_web_scheme') or 'http').strip() or 'http',
            'server_web_host': str(payload.get('server_web_host') or payload.get('server_host') or '').strip(),
            'warnings': build_result.get('warnings') or [],
        }
        self._write_metadata(file_name, record)
        return self.get_output_record(file_name)

    def get_output_record(self, filename: str) -> dict:
        file_name = self._normalize_filename(filename)
        file_path = self._safe_join_output(file_name)
        if not os.path.isfile(file_path):
            raise FileNotFoundError('File not found')

        metadata = self._read_metadata(file_name)
        stat = os.stat(file_path)
        build_time = str(metadata.get('build_time') or metadata.get('created_at') or '').strip()
        if not build_time:
            build_time = datetime.fromtimestamp(stat.st_mtime).isoformat()

        record = {
            'file_name': file_name,
            'size': int(stat.st_size),
            'build_time': build_time,
            'build_version': str(metadata.get('build_version') or '').strip(),
            'builder': str(metadata.get('builder') or '').strip(),
            'source': str(metadata.get('source') or '').strip(),
            'target_os': str(metadata.get('target_os') or '').strip(),
            'target_arch': str(metadata.get('target_arch') or '').strip(),
            'server_host': str(metadata.get('server_host') or '').strip(),
            'server_port': int(metadata.get('server_port') or 0),
            'web_port': int(metadata.get('web_port') or 0),
            'file_transfer_port': int(metadata.get('file_transfer_port') or 0),
            'server_web_scheme': str(metadata.get('server_web_scheme') or 'http').strip() or 'http',
            'server_web_host': str(metadata.get('server_web_host') or metadata.get('server_host') or '').strip(),
            'warnings': metadata.get('warnings') or [],
        }
        return record

    def list_outputs(self) -> list:
        results = []
        for entry in os.listdir(self.output_dir):
            if entry.startswith('.'):
                continue
            file_path = os.path.join(self.output_dir, entry)
            if not os.path.isfile(file_path):
                continue
            try:
                results.append(self.get_output_record(entry))
            except Exception:
                continue

        results.sort(key=lambda item: str(item.get('build_time') or ''), reverse=True)
        return results

    def delete_output(self, filename: str) -> dict:
        file_name = self._normalize_filename(filename)
        file_path = self._safe_join_output(file_name)
        metadata_path = self._metadata_path(file_name)

        if not os.path.isfile(file_path):
            raise FileNotFoundError('File not found')

        os.remove(file_path)
        if os.path.isfile(metadata_path):
            os.remove(metadata_path)

        return {'deleted': True, 'file_name': file_name}