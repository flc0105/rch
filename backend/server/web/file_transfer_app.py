import os
import time

from flask import Flask, request, send_file

from core.transfer_settings import DEFAULT_HTTP_TRANSFER_BUFFER_SIZE
from server.config.config import WEB_HTTP_UPLOAD_MAX_BYTES
from server.web.api_response import WebApiResponder
from server.web.artifact_upload import save_uploaded_artifact_from_request


def create_file_transfer_app(server_instance):
    """
    Client <-> Server 专用文件传输 WSGI 应用。

    该应用由 Werkzeug 直接监听独立端口，不挂载到 FastAPI/ASGI，避免大文件
    request body 经过 WSGIMiddleware 聚合。Remote File Browser 的文件本体也直接走该端口。
    """
    app = Flask('rch_file_transfer')
    app.config['MAX_CONTENT_LENGTH'] = WEB_HTTP_UPLOAD_MAX_BYTES

    artifact_api = server_instance.web_service.artifact_api
    command_execution_api = server_instance.web_service.command_execution_api
    transfer_api = server_instance.web_service.transfer_api
    responder = WebApiResponder()

    @app.after_request
    def add_browser_transfer_cors_headers(response):
        if (request.path or '').startswith('/api/transfers/browser-upload/'):
            origin = str(request.headers.get('Origin') or '').strip()
            if origin:
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-RCH-Transfer-Token'
            response.headers['Access-Control-Max-Age'] = '600'
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/api/transfers/browser-upload/<transfer_id>/content', methods=['POST', 'OPTIONS'])
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

    @app.post('/api/files/upload')
    def upload_file():
        return responder.json_endpoint(
            lambda: save_uploaded_artifact_from_request(artifact_api),
            default_error_status=500,
        )

    @app.get('/api/upload-tmp/<temp_id>/<filename>')
    def download_upload_tmp_file(temp_id, filename):
        try:
            file_path = artifact_api.get_upload_temp_file_path(temp_id, filename)
            return send_file(
                file_path,
                as_attachment=True,
                download_name=os.path.basename(file_path),
            )
        except Exception as exc:
            return responder.map_common_error(exc)

    @app.errorhandler(413)
    def file_too_large(_):
        return responder.fail('File is too large', 413)

    return app
