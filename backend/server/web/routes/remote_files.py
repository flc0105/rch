from flask import Blueprint, request

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload, get_optional_remote_path, get_optional_tab_id, parse_paging_args


def create_remote_files_blueprint(server_instance):
    blueprint = Blueprint('remote_files', __name__)
    web_service = server_instance.web_service
    remote_file_api = web_service.remote_file_api
    responder = WebApiResponder()

    @blueprint.get('/api/connections/<client_id>/remote-files')
    def browse_remote_files(client_id):
        def _execute():
            paging = parse_paging_args(default_page=1, default_page_size=100)
            search_keyword = (request.args.get('search') or '').strip()
            recursive_raw = (request.args.get('recursive') or '').strip().lower()
            return remote_file_api.browse_remote_directory(
                client_id,
                get_optional_remote_path(),
                page=paging['page'],
                page_size=paging['page_size'],
                show_hidden=paging['show_hidden'],
                search_keyword=search_keyword,
                recursive_search=recursive_raw in ('1', 'true', 'yes', 'on'),
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/mkdir')
    def create_remote_directory(client_id):
        def _execute():
            payload = get_json_payload()
            path = (payload.get('path') or '').strip()
            if not path:
                raise ValueError('path is required')
            return remote_file_api.create_remote_directory(client_id, path)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/rename')
    def rename_remote_path(client_id):
        def _execute():
            payload = get_json_payload()
            old_path = (payload.get('old_path') or '').strip()
            new_name = (payload.get('new_name') or '').strip()

            if not old_path:
                raise ValueError('old_path is required')
            if not new_name:
                raise ValueError('new_name is required')

            return remote_file_api.rename_remote_path(client_id, old_path, new_name)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/connections/<client_id>/remote-files')
    def delete_remote_file_or_directory(client_id):
        def _execute():
            path = get_optional_remote_path()
            if not path:
                raise ValueError('path is required')
            return remote_file_api.delete_remote_path(client_id, path)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/download')
    def download_remote_file(client_id):
        def _execute():
            path = get_optional_remote_path()
            if not path:
                raise ValueError('path is required')
            return remote_file_api.download_remote_file(client_id, path, tab_id=get_optional_tab_id())

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/download-zip')
    def download_remote_paths_as_zip(client_id):
        def _execute():
            payload = get_json_payload()
            paths = payload.get('paths') or []
            archive_name = (payload.get('archive_name') or '').strip()

            if not isinstance(paths, list) or not paths:
                raise ValueError('paths is required')

            return remote_file_api.download_remote_paths_as_zip(
                client_id,
                paths,
                archive_name,
                tab_id=get_optional_tab_id(),
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/create-zip')
    def create_remote_zip(client_id):
        def _execute():
            payload = get_json_payload()
            paths = payload.get('paths') or []
            destination_dir = (payload.get('destination_dir') or '').strip()
            archive_name = (payload.get('archive_name') or '').strip()

            if not isinstance(paths, list) or not paths:
                raise ValueError('paths is required')
            if not destination_dir:
                raise ValueError('destination_dir is required')

            return remote_file_api.create_remote_zip(
                client_id,
                paths,
                destination_dir,
                archive_name,
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/zip-peek')
    def peek_remote_zip(client_id):
        def _execute():
            payload = get_json_payload()
            path = (payload.get('path') or '').strip()
            if not path:
                raise ValueError('path is required')
            return remote_file_api.peek_remote_zip(client_id, path)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/zip-entry')
    def read_remote_zip_entry(client_id):
        def _execute():
            payload = get_json_payload()
            path = (payload.get('path') or '').strip()
            entry_name = str(payload.get('entry_name') or '')
            if not path:
                raise ValueError('path is required')
            if not entry_name:
                raise ValueError('entry_name is required')
            return remote_file_api.read_remote_zip_entry(client_id, path, entry_name)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/extract-zip')
    def extract_remote_zip(client_id):
        def _execute():
            payload = get_json_payload()
            path = (payload.get('path') or '').strip()
            destination_dir = (payload.get('destination_dir') or '').strip()
            if not path:
                raise ValueError('path is required')
            if not destination_dir:
                raise ValueError('destination_dir is required')
            return remote_file_api.extract_remote_zip(client_id, path, destination_dir)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/connections/<client_id>/remote-files/batch')
    def delete_remote_files_batch(client_id):
        def _execute():
            payload = get_json_payload()
            paths = payload.get('paths') or []
            if not isinstance(paths, list) or not paths:
                raise ValueError('paths is required and must be a non-empty list')
            return remote_file_api.delete_remote_paths(client_id, paths)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/paste')
    def paste_remote_files(client_id):
        def _execute():
            payload = get_json_payload()
            paths = payload.get('paths') or []
            destination_dir = (payload.get('destination_dir') or '').strip()
            operation = (payload.get('operation') or 'copy').strip().lower()

            if not isinstance(paths, list) or not paths:
                raise ValueError('paths is required and must be a non-empty list')
            if not destination_dir:
                raise ValueError('destination_dir is required')
            if operation not in ('copy', 'move'):
                raise ValueError('operation must be copy or move')

            return remote_file_api.paste_remote_paths(client_id, paths, destination_dir, operation)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/preview')
    def preview_remote_file(client_id):
        def _execute():
            payload = get_json_payload()
            path = (payload.get('path') or '').strip()
            if not path:
                raise ValueError('path is required')
            return remote_file_api.preview_remote_file(client_id, path, tab_id=get_optional_tab_id())

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/remote-files/save')
    def save_remote_file(client_id):
        def _execute():
            payload = get_json_payload()
            path = (payload.get('path') or '').strip()
            content = payload.get('content', '')
            encoding = (payload.get('encoding') or 'utf-8').strip()

            if not path:
                raise ValueError('path is required')

            return remote_file_api.save_remote_file(
                client_id,
                path,
                content,
                encoding,
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint