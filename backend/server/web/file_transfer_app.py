from flask import Blueprint, request

from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous


def create_browser_upload_blueprint(server_instance):
    """Raw, chunked browser upload on the main direct Werkzeug HTTP server."""
    app = Blueprint('browser_upload_content', __name__)
    uploads = server_instance.web_service.assembly.browser_upload_service
    responder = WebApiResponder()

    @app.route('/api/transfers/browser-upload/<transfer_id>/content', methods=['POST', 'OPTIONS'])
    @allow_anonymous
    def upload_browser_transfer(transfer_id):
        if request.method == 'OPTIONS':
            return '', 204
        upload_token = str(request.headers.get('X-RCH-Transfer-Token') or '').strip()
        grant = uploads.consume_browser_upload_grant(transfer_id, upload_token)
        if not grant:
            return responder.fail('Invalid or expired browser upload transfer token', 403)
        return responder.json_endpoint(lambda: uploads.receive_content(
            transfer_id, grant, lambda size: request.stream.read(size), content_length=request.content_length,
            max_content_length=request.max_content_length), default_error_status=500)

    return app
