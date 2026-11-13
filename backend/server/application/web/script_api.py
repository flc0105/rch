from server.application.scripts.script_run_service import prepare_script_control


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

    def run_script(self, client_id: str, script_name: str, params=None, tab_id: str = '',
                   presentation: str = '', run_id: str = '', operation_id: str = ''):
        normalized_script_name = str(script_name or '').strip()
        if not normalized_script_name:
            raise ValueError('script_name is required')
        normalized_presentation = str(presentation or '').strip().lower()
        if normalized_presentation not in {'dialog', 'terminal'}:
            raise ValueError('presentation must be dialog or terminal')
        normalized_run_id = str(run_id or '').strip()
        if normalized_presentation == 'dialog' and not normalized_run_id:
            raise ValueError('run_id is required for dialog presentation')
        request = prepare_script_control(self.script_catalog_service.scripts_root_dir, normalized_script_name, params if params is not None else {})
        return self.command_execution_api.submit_web_script(
            client_id, request['script_name'], request['params'], tab_id=tab_id,
            presentation=normalized_presentation, run_id=normalized_run_id,
            operation_id=operation_id,
        )
