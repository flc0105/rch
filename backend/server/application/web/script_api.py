import json

from core.protocol.structured_arg_codec import encode_structured_arg
from core.utils.script_metadata import resolve_script_params
from server.application.auth.script_grant_service import SCRIPT_GRANT_REQUEST_KEY


class WebScriptApi:
    def __init__(self, command_execution_api, script_catalog_service):
        self.command_execution_api = command_execution_api
        self.script_catalog_service = script_catalog_service

    def list_script_catalog(self):
        catalog = self.script_catalog_service.get_catalog() or {}
        items = []
        for item in catalog.get('items') or []:
            if not isinstance(item, dict):
                continue
            script_name = str(item.get('script_name') or item.get('name') or '').strip()
            if not script_name:
                continue
            items.append({
                **item,
                'script_name': script_name,
                'display_name': str(item.get('display_name') or script_name.split('/')[-1]).strip() or script_name,
                'description': str(item.get('description') or '').strip(),
                'metadata': item.get('metadata') or {},
                'source': 'script',
            })

        directories = []
        for item in catalog.get('directories') or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get('path') or '').strip()
            directories.append({
                **item,
                'path': path,
                'label': str(item.get('label') or (path.split('/')[-1] if path else 'root')).strip() or 'root',
                'key': str(item.get('key') or f'dir:{path or "."}').strip() or f'dir:{path or "."}',
                'kind': 'directory',
            })

        return {
            'items': items,
            'directories': directories,
        }

    def get_script_content(self, script_name: str) -> str:
        return self.script_catalog_service.get_script_content(script_name)

    def save_script_content(self, script_name: str, content: str):
        return self.script_catalog_service.save_script(script_name, content)

    def upload_script(self, file_storage, directory: str = ''):
        return self.script_catalog_service.upload_script(file_storage, directory=directory)

    def create_directory(self, directory: str):
        return self.script_catalog_service.create_directory(directory)

    def rename_directory(self, directory: str, new_directory: str):
        return self.script_catalog_service.rename_directory(directory, new_directory)

    def delete_directory(self, directory: str):
        return self.script_catalog_service.delete_directory(directory)

    def rename_script(self, script_name: str, new_name: str):
        return self.script_catalog_service.rename_script(script_name, new_name)

    def delete_script(self, script_name: str):
        return self.script_catalog_service.delete_script(script_name)

    def _build_script_grant_request(self, metadata: dict, script_name: str) -> dict:
        api_grants = metadata.get('api_grants') if isinstance(metadata, dict) else None
        if not api_grants:
            return {}
        return {
            'script_name': script_name,
            'api_grants': api_grants,
        }

    def _strip_reserved_params(self, params: dict) -> dict:
        normalized = dict(params or {}) if isinstance(params, dict) else {}
        normalized.pop(SCRIPT_GRANT_REQUEST_KEY, None)
        normalized.pop('script_grant_request', None)
        return normalized

    def run_script(self, client_id: str, script_name: str, params=None, tab_id: str = ''):
        normalized_script_name = str(script_name or '').strip()
        if not normalized_script_name:
            raise ValueError('script_name is required')
        metadata = {}
        for item in self.script_catalog_service.list_scripts() or []:
            if str(item.get('script_name') or '').strip() == normalized_script_name:
                metadata = item.get('metadata') or {}
                break
        normalized_params = resolve_script_params(metadata, params if isinstance(params, dict) else {})
        normalized_params = self._strip_reserved_params(normalized_params)
        payload = {
            'script_name': normalized_script_name,
            'params': normalized_params,
        }
        grant_request = self._build_script_grant_request(metadata, normalized_script_name)
        if grant_request:
            payload['script_grant_request'] = grant_request
        return self.command_execution_api.submit_web_command(
            client_id,
            f'run_script {encode_structured_arg(payload)}',
            tab_id=tab_id,
        )