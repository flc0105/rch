import os

from flask import Blueprint, send_file

from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous
from server.web.request_parsers import get_json_payload

def _remove_temp_file(file_path: str):
    try:
        if file_path and os.path.isfile(file_path):
            os.remove(file_path)
    except OSError:
        pass


def create_agent_blueprint(server_instance):
    blueprint = Blueprint('agent', __name__)
    web_service = server_instance.web_service
    agent_api = web_service.agent_api
    responder = WebApiResponder()

    @blueprint.post('/api/agent/build')
    @allow_anonymous
    def build_agent():
        """构建 Agent"""

        def _execute():
            payload = get_json_payload()
            server_host = (payload.get('server_host') or '').strip()
            server_port = payload.get('server_port')
            web_port = payload.get('web_port')
            file_transfer_port = payload.get('file_transfer_port')
            target_os = (payload.get('target_os') or 'mac').strip()
            builder = (payload.get('builder') or 'pyinstaller').strip()
            target_arch = (payload.get('target_arch') or '').strip()
            server_web_scheme = (payload.get('server_web_scheme') or 'http').strip() or 'http'
            server_web_host = (payload.get('server_web_host') or server_host).strip() or server_host
            source = (payload.get('source') or 'manual').strip() or 'manual'

            if not server_host:
                raise ValueError('server_host is required')
            if not server_port:
                raise ValueError('server_port is required')
            if not web_port:
                raise ValueError('web_port is required')

            try:
                server_port = int(server_port)
            except ValueError:
                raise ValueError('server_port must be integer')

            try:
                web_port = int(web_port)
            except ValueError:
                raise ValueError('web_port must be integer')

            if file_transfer_port:
                try:
                    file_transfer_port = int(file_transfer_port)
                except ValueError:
                    raise ValueError('file_transfer_port must be integer')

            result = agent_api.build_agent(
                server_host,
                server_port,
                web_port,
                file_transfer_port,
                target_os,
                builder,
                target_arch,
                server_web_scheme,
                server_web_host,
                source,
            )
            result['download_url'] = f'/api/agent/download/{result["file_name"]}'
            return result

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.get('/api/agent/outputs')
    def list_agent_outputs():
        return responder.json_endpoint(
            lambda: agent_api.list_agent_outputs(),
            default_error_status=500,
        )

    @blueprint.delete('/api/agent/outputs/<filename>')
    def delete_agent_output(filename):
        return responder.json_endpoint(
            lambda: agent_api.delete_agent_output(filename),
            default_error_status=500,
        )

    @blueprint.get('/api/agent/download/<filename>')
    @allow_anonymous
    def download_agent(filename):
        """下载构建好的 Agent"""
        try:
            file_path = agent_api.get_built_agent_file_path(filename)
            return send_file(
                file_path,
                as_attachment=True,
                download_name=filename,
            )
        except FileNotFoundError as e:
            return responder.fail(str(e), 404)
        except Exception as e:
            return responder.map_common_error(e)

    @blueprint.get('/api/agent/platform')
    def get_agent_platform():
        return responder.json_endpoint(
            lambda: agent_api.get_server_platform(),
            default_error_status=500,
        )

    @blueprint.post('/api/agent/loader/report')
    @allow_anonymous
    def ingest_loader_report():
        return responder.json_endpoint(
            lambda: agent_api.ingest_loader_report(get_json_payload()),
            default_error_status=500,
        )

    @blueprint.post('/api/agent/bootstrap')
    @allow_anonymous
    def generate_bootstrap():
        file_info = None
        try:
            file_info = agent_api.generate_bootstrap_file(get_json_payload())
            response = send_file(
                file_info['file_path'],
                as_attachment=True,
                download_name=file_info['download_name'],
                mimetype=file_info['mimetype'],
            )
            response.call_on_close(lambda: _remove_temp_file(file_info['file_path']))
            return response
        except Exception as e:
            if file_info:
                _remove_temp_file(file_info.get('file_path') or '')
            return responder.map_common_error(e)

    @blueprint.post('/api/agent/bootstrap/ps1')
    @allow_anonymous
    def generate_bootstrap_ps1():
        file_info = None
        try:
            file_info = agent_api.generate_bootstrap_ps1_file(get_json_payload())
            response = send_file(
                file_info['file_path'],
                as_attachment=True,
                download_name=file_info['download_name'],
                mimetype=file_info['mimetype'],
            )
            response.call_on_close(lambda: _remove_temp_file(file_info['file_path']))
            return response
        except Exception as e:
            if file_info:
                _remove_temp_file(file_info.get('file_path') or '')
            return responder.map_common_error(e)

    return blueprint
