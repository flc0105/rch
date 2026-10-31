import time

from flask import Blueprint, request

from core.transfer_settings import DEFAULT_HTTP_TRANSFER_BUFFER_SIZE
from server.web.api_response import WebApiResponder
from server.web.auth_guard import allow_anonymous


def create_browser_upload_blueprint(server_instance):
    """Raw, chunked browser upload on the main direct Werkzeug HTTP server."""
    app = Blueprint('browser_upload_content', __name__)

    artifact_api = server_instance.web_service.artifact_api
    command_execution_api = server_instance.web_service.command_execution_api
    transfer_api = server_instance.web_service.transfer_api
    responder = WebApiResponder()

    @app.route('/api/transfers/browser-upload/<transfer_id>/content', methods=['POST', 'OPTIONS'])
    @allow_anonymous
    def upload_browser_transfer(transfer_id):
        if request.method == 'OPTIONS':
            return '', 204

        upload_token = str(request.headers.get('X-RCH-Transfer-Token') or '').strip()
        grant = transfer_api.consume_browser_upload_grant(transfer_id, upload_token)
        if not grant:
            return responder.fail('Invalid or expired browser upload transfer token', 403)

        tab_id = str(grant.get('tab_id') or '').strip()
        client_id = str(grant.get('client_id') or '').strip()
        target_path = str(grant.get('destination_path') or '').strip()
        filename = str(grant.get('filename') or '').strip() or 'upload.bin'
        expected_total = grant.get('total_bytes')
        temp_path = ''

        def _execute():
            nonlocal temp_path
            try:
                normalized_expected_total = None
                if expected_total not in (None, ''):
                    try:
                        normalized_expected_total = max(0, int(expected_total))
                    except Exception:
                        normalized_expected_total = None

                request_content_length = request.content_length
                if (
                    normalized_expected_total is not None
                    and request_content_length is not None
                    and int(request_content_length) != normalized_expected_total
                ):
                    raise ValueError(
                        f'Browser upload size mismatch: expected {normalized_expected_total} bytes, '
                        f'request declared {int(request_content_length)} bytes'
                    )

                temp_path, safe_name = artifact_api.create_upload_temp_path(filename)
                received_bytes = 0
                last_progress_sync = 0.0

                with open(temp_path, 'wb', buffering=DEFAULT_HTTP_TRANSFER_BUFFER_SIZE) as output_file:
                    while True:
                        if transfer_api.is_browser_upload_cancel_requested(transfer_id):
                            raise RuntimeError('Browser upload cancelled')

                        chunk = request.stream.read(DEFAULT_HTTP_TRANSFER_BUFFER_SIZE)
                        if not chunk:
                            break

                        if transfer_api.is_browser_upload_cancel_requested(transfer_id):
                            raise RuntimeError('Browser upload cancelled')

                        output_file.write(chunk)
                        received_bytes += len(chunk)

                        now = time.monotonic()
                        if now - last_progress_sync >= 0.25:
                            transfer_api.update_browser_upload_progress(
                                transfer_id,
                                transferred_bytes=received_bytes,
                                total_bytes=expected_total,
                                tab_id=tab_id,
                            )
                            last_progress_sync = now

                if normalized_expected_total is not None and received_bytes != normalized_expected_total:
                    raise ValueError(
                        f'Browser upload size mismatch: expected {normalized_expected_total} bytes, '
                        f'received {received_bytes} bytes'
                    )

                transfer_api.update_browser_upload_progress(
                    transfer_id,
                    transferred_bytes=received_bytes,
                    total_bytes=normalized_expected_total if normalized_expected_total is not None else received_bytes,
                    tab_id=tab_id,
                )
                transfer_api.mark_browser_upload_staged(
                    transfer_id,
                    total_bytes=received_bytes,
                    tab_id=tab_id,
                )
                transfer_api.clear_browser_upload_runtime(transfer_id)

                current_transfer = transfer_api.transfer_service.get_transfer(transfer_id, tab_id=tab_id)
                if not current_transfer or current_transfer.get('state') != 'running':
                    raise RuntimeError('Browser upload cancelled')

                return command_execution_api.submit_web_upload(
                    client_id,
                    temp_path,
                    safe_name,
                    target_path,
                    tab_id=tab_id,
                    transfer_id=transfer_id,
                )
            except Exception as exc:
                transfer_api.clear_browser_upload_runtime(transfer_id)
                if temp_path:
                    artifact_api.cleanup_upload_temp_file(temp_path)
                try:
                    transfer_api.fail_upload_transfer(transfer_id, str(exc), tab_id=tab_id)
                except Exception:
                    pass
                raise

        return responder.json_endpoint(_execute, default_error_status=500)

    return app
