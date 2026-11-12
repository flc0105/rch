from flask import Blueprint

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload


def create_system_inspection_blueprint(server_instance):
    blueprint = Blueprint('system_inspection', __name__)
    web_service = server_instance.web_service
    connection_api = web_service.connection_api
    process_control_api = web_service.process_control_api
    responder = WebApiResponder()

    @blueprint.get('/api/connections/<client_id>/system-paths')
    def get_system_paths(client_id):
        """获取客户端系统路径"""
        return responder.json_endpoint(
            lambda: connection_api.get_system_paths(client_id),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/processes/<int:pid>/kill')
    def kill_process(client_id, pid):
        """终止进程"""
        return responder.json_endpoint(
            lambda: process_control_api.kill_process(client_id, pid, get_json_payload().get('name', '')),
            default_error_status=500,
        )

    @blueprint.post('/api/connections/<client_id>/apps/<int:pid>/kill')
    def kill_app(client_id, pid):
        """终止应用"""
        return responder.json_endpoint(
            lambda: process_control_api.kill_app(client_id, pid, get_json_payload().get('name', '')),
            default_error_status=500,
        )

    return blueprint
