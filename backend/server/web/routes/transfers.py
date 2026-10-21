from flask import Blueprint, request

from server.web.api_response import WebApiResponder
from server.web.request_parsers import get_json_payload, get_optional_tab_id


def create_transfers_blueprint(server_instance):
    blueprint = Blueprint('transfers', __name__)
    transfer_api = server_instance.web_service.transfer_api
    responder = WebApiResponder()

    @blueprint.get('/api/transfers')
    def list_transfers():
        return responder.json_endpoint(
            lambda: transfer_api.list_transfers(tab_id=get_optional_tab_id()),
            default_error_status=500,
        )

    @blueprint.post('/api/transfers/browser-upload')
    def create_browser_upload_transfer():
        def _execute():
            payload = get_json_payload()
            return transfer_api.create_browser_upload_transfer(
                client_id=payload.get('client_id') or '',
                filename=payload.get('filename') or '',
                total_bytes=payload.get('total_bytes'),
                destination_path=payload.get('destination_path') or '',
                tab_id=get_optional_tab_id(),
                origin='web_ui' if request.headers.get('X-RCH-Origin') == 'web_ui' else 'web_api',
                feature=request.headers.get('X-RCH-Feature') if request.headers.get('X-RCH-Feature') in ('remote_files', 'remote_file_picker') else 'remote_files',
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    @blueprint.post('/api/transfers/<transfer_id>/cancel')
    def cancel_transfer(transfer_id):
        return responder.json_endpoint(
            lambda: transfer_api.cancel_transfer(
                transfer_id,
                tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    @blueprint.delete('/api/transfers/recent')
    def clear_recent_transfers():
        return responder.json_endpoint(
            lambda: transfer_api.clear_recent_transfers(tab_id=get_optional_tab_id()),
            default_error_status=500,
        )

    @blueprint.delete('/api/transfers/<transfer_id>')
    def delete_recent_transfer(transfer_id):
        return responder.json_endpoint(
            lambda: transfer_api.delete_recent_transfer(
                transfer_id,
                tab_id=get_optional_tab_id(),
            ),
            default_error_status=500,
        )

    @blueprint.patch('/api/transfers/<transfer_id>/browser-upload')
    def update_browser_upload_transfer(transfer_id):
        def _execute():
            payload = get_json_payload()
            state = str(payload.get('state') or 'running').strip().lower()
            if state == 'failed':
                return transfer_api.fail_browser_upload_transfer(
                    transfer_id,
                    payload.get('error') or 'Browser upload failed',
                    tab_id=get_optional_tab_id(),
                )

            return transfer_api.update_browser_upload_progress(
                transfer_id,
                transferred_bytes=payload.get('transferred_bytes'),
                total_bytes=payload.get('total_bytes'),
                tab_id=get_optional_tab_id(),
            )

        return responder.json_endpoint(_execute, default_error_status=500)

    return blueprint
