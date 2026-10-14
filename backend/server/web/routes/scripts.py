from flask import Blueprint, Response, request

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload, get_optional_tab_id


def create_script_blueprint(server_instance):
    blueprint = Blueprint('scripts', __name__)
    web_service = server_instance.web_service
    script_api = web_service.script_api
    responder = WebApiResponder()

    @blueprint.get('/api/scripts/catalog')
    def list_scripts():
        return responder.json_endpoint(
            lambda: script_api.list_script_catalog(),
            default_error_status=500,
        )

    @blueprint.get('/api/scripts/download')
    def download_script():
        script_name = request.args.get('name', '').strip()
        if not script_name:
            return responder.fail('script name is required', 400)
        try:
            content = script_api.get_script_content(script_name)
            return Response(content, mimetype='text/plain')
        except FileNotFoundError as e:
            return responder.fail(str(e), 404)
        except Exception as e:
            return responder.fail(str(e), 500)

    @blueprint.post('/api/scripts/save')
    def save_script():
        def _execute():
            payload = get_json_payload()
            name = (payload.get('name') or '').strip()
            content = payload.get('content', '')
            if not name:
                raise ValueError('script name is required')
            if content is None:
                raise ValueError('script content is required')
            return script_api.save_script_content(name, content)
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/scripts/upload')
    def upload_script():
        def _execute():
            file_obj = request.files.get('file')
            directory = (request.form.get('directory') or '').strip()
            if file_obj is None:
                raise ValueError('file is required')
            return script_api.upload_script(file_obj, directory=directory)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/scripts/folders')
    def create_script_folder():
        def _execute():
            payload = get_json_payload()
            directory = (payload.get('directory') or '').strip()
            if not directory:
                raise ValueError('directory is required')
            return script_api.create_directory(directory)
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/scripts/folders/rename')
    def rename_script_folder():
        def _execute():
            payload = get_json_payload()
            directory = (payload.get('directory') or '').strip()
            new_directory = (payload.get('new_directory') or '').strip()
            if not directory:
                raise ValueError('directory is required')
            if not new_directory:
                raise ValueError('new directory is required')
            return script_api.rename_directory(directory, new_directory)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/scripts/folders')
    def delete_script_folder():
        def _execute():
            payload = get_json_payload()
            directory = (payload.get('directory') or '').strip()
            if not directory:
                raise ValueError('directory is required')
            return script_api.delete_directory(directory)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/scripts/rename')
    def rename_script():
        def _execute():
            payload = get_json_payload()
            name = (payload.get('name') or '').strip()
            new_name = (payload.get('new_name') or '').strip()
            if not name:
                raise ValueError('script name is required')
            if not new_name:
                raise ValueError('new script name is required')
            return script_api.rename_script(name, new_name)
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/scripts/delete')
    def delete_script():
        def _execute():
            payload = get_json_payload()
            name = (payload.get('name') or '').strip()
            if not name:
                raise ValueError('script name is required')
            return script_api.delete_script(name)
        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/scripts/run')
    def run_script(client_id):
        def _execute():
            payload = get_json_payload()
            script_name = (payload.get('script_name') or '').strip()
            params = payload.get('params') or {}
            if not script_name:
                raise ValueError('script_name is required')
            if params is not None and not isinstance(params, dict):
                raise ValueError('params must be an object')
            return script_api.run_script(
                client_id,
                script_name,
                params=params,
                tab_id=get_optional_tab_id(),
                presentation=payload.get('presentation'),
                run_id=payload.get('run_id'),
            )
        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
