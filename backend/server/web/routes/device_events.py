from flask import Blueprint

from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous
from server.web.request_parsers import get_json_payload


def create_device_events_blueprint(server_instance):
    blueprint = Blueprint('device_events', __name__)
    device_event_api = server_instance.web_service.device_event_api
    responder = WebApiResponder()

    @blueprint.post('/api/device-events')
    @allow_anonymous
    def ingest_device_event():
        return responder.json_endpoint(
            lambda: device_event_api.ingest(get_json_payload()),
            default_error_status=400,
        )

    return blueprint
