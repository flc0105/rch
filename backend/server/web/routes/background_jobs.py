from flask import Blueprint, request, Response

from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous
from server.web.request_parsers import get_json_payload


def create_background_job_blueprint(server_instance):
    blueprint = Blueprint('background_jobs', __name__)
    web_service = server_instance.web_service
    job_api = web_service.job_api
    responder = WebApiResponder()

    @blueprint.get('/api/jobs/list')
    @allow_anonymous
    def list_jobs():
        """列出所有可用的任务"""
        return responder.json_endpoint(
            lambda: job_api.list_jobs(),
            default_error_status=500,
        )

    @blueprint.get('/api/jobs/download')
    @allow_anonymous
    def download_job():
        """下载任务内容（供 Client 使用）"""
        job_name = request.args.get('name', '').strip()
        if not job_name:
            return responder.fail('job name is required', 400)

        try:
            content = job_api.get_job_content(job_name)
            return Response(content, mimetype='text/plain')
        except FileNotFoundError as e:
            return responder.fail(str(e), 404)
        except Exception as e:
            return responder.fail(str(e), 500)

    @blueprint.post('/api/jobs/save')
    def save_job():
        def _execute():
            payload = get_json_payload()
            name = (payload.get('name') or '').strip()
            content = payload.get('content', '')

            if not name:
                raise ValueError('job name is required')
            if content is None:
                raise ValueError('job content is required')

            return job_api.save_job_content(name, content)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/jobs/upload')
    def upload_job():
        def _execute():
            file_obj = request.files.get('file')
            if file_obj is None:
                raise ValueError('file is required')
            return job_api.upload_job(file_obj)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.delete('/api/jobs/delete')
    def delete_job():
        def _execute():
            payload = get_json_payload()
            name = (payload.get('name') or '').strip()
            if not name:
                raise ValueError('job name is required')

            return job_api.delete_job(name)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/connections/<client_id>/background-jobs/modules')
    def list_available_background_jobs(client_id):
        return responder.json_endpoint(
            lambda: job_api.list_available_background_jobs(client_id),
            default_error_status=500,
        )

    @blueprint.get('/api/connections/<client_id>/background-jobs/catalog')
    def list_background_job_catalog(client_id):
        return responder.json_endpoint(
            lambda: job_api.list_background_job_catalog(client_id),
            default_error_status=500,
        )

    @blueprint.get('/api/connections/<client_id>/background-jobs')
    def list_background_jobs(client_id):
        return responder.json_endpoint(
            lambda: job_api.list_background_jobs(client_id),
            default_error_status=500,
        )

    @blueprint.get('/api/connections/<client_id>/background-jobs/<job_id>')
    def get_background_job(client_id, job_id):
        return responder.json_endpoint(
            lambda: job_api.get_background_job(client_id, job_id),
            default_error_status=500,
        )

    @blueprint.delete('/api/connections/<client_id>/background-jobs/<job_id>')
    def delete_background_job_record(client_id, job_id):
        return responder.json_endpoint(
            lambda: job_api.delete_background_job_record(client_id, job_id),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/background-jobs/start')
    def start_background_job(client_id):
        def _execute():
            payload = get_json_payload()
            job_name = (payload.get('job_name') or '').strip()
            params = payload.get('params') or {}
            execution_mode = str(payload.get('execution_mode') or 'inproc').strip() or 'inproc'
            if not job_name:
                raise ValueError('job_name is required')
            if params is not None and not isinstance(params, dict):
                raise ValueError('params must be an object')

            return job_api.start_background_job(
                client_id,
                job_name,
                params=params,
                execution_mode=execution_mode,
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/connections/<client_id>/background-jobs/stop')
    def stop_background_job(client_id):
        def _execute():
            payload = get_json_payload()
            job_key = (payload.get('job_key') or '').strip()
            if not job_key:
                raise ValueError('job_key is required')
            return job_api.stop_background_job(client_id, job_key)

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/background-jobs/report')
    @allow_anonymous
    def report_background_job_event():
        def _execute():
            payload = get_json_payload()
            return job_api.ingest_background_job_report(payload)

        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
