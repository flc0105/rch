from flask import Blueprint, request

from server.web.api_response import WebApiResponder


def create_notification_history_blueprint(server_instance):
    blueprint = Blueprint('notification_history', __name__)
    notification_api = server_instance.web_service.notification_history_api
    responder = WebApiResponder()

    @blueprint.get('/api/notifications/history')
    def get_notification_history():
        return responder.json_endpoint(
            notification_api.get_history,
            default_error_status=500,
        )

    @blueprint.delete('/api/notifications/history/<notification_id>')
    def delete_notification_history(notification_id):
        return responder.json_endpoint(
            lambda: notification_api.delete_notification(notification_id),
            default_error_status=500,
        )

    @blueprint.delete('/api/notifications/history')
    def clear_notification_history():
        return responder.json_endpoint(
            lambda: notification_api.clear_history(request.args.get('type', '')),
            default_error_status=500,
        )

    return blueprint
