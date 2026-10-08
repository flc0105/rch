import json
import os
import shutil
import time

from client.commands.runtime.context import CommandCancelledError
from client.commands.strategies.http_transfer.factory import build_http_transfer_strategy
from client.http.client_api import ClientApiClient
from core.protocol.message_types import MSG_TYPE_TRANSFER_UPDATE
from core.utils.formatting import format_bytes
from core.utils.output_marker import success


class CommandHttpFileTransferService:
    """
    HTTP 文件传输服务。

    职责：
    - 从 CommandFileWebMixin 中抽离 HTTP 上传/下载基础设施
    - 显式承接 HTTP 传输策略、表单构造、响应解析等逻辑
    - 让命令 mixin 只保留“命令入口 + 参数组织”，减少横向隐式耦合
    """

    PROGRESS_REPORT_INTERVAL_SECONDS = 0.25

    def __init__(self, owner, archive_service=None, client_api=None):
        self.owner = owner
        self.archive_service = archive_service
        self.client_api = client_api or getattr(owner, 'client_api', None) or ClientApiClient()

    def get_transfer_strategy(self):
        transfer_mode = getattr(self.owner, 'HTTP_TRANSFER_MODE', '')
        return build_http_transfer_strategy(self.owner, transfer_mode)

    def build_http_upload_form_data(
        self,
        *,
        artifact_type: str,
        category: str,
        extra: dict | None = None,
        transfer_buffer_size: int | None = None,
    ) -> dict:
        client_id = getattr(self.owner.socket, 'client_id', '') or ''

        payload = {
            'artifact_type': (artifact_type or 'files').strip() or 'files',
            'category': (category or '').strip() or 'default',
            'client_id': client_id,
            'source_command_id': self.owner.command_id if self.owner.command_id is not None else '',
        }

        if isinstance(extra, dict) and extra:
            payload['extra'] = json.dumps(extra, ensure_ascii=False)
        if transfer_buffer_size is not None:
            payload['transfer_buffer_size'] = max(int(transfer_buffer_size), 1)

        return payload

    def parse_http_upload_response(self, response):
        return self.client_api.try_parse_json(response)

    def build_http_upload_start_message(self, file_path: str, file_size: int) -> str:
        return f"Uploading: {os.path.basename(file_path)} ({format_bytes(file_size, max_unit='TB')})"

    def build_http_upload_success_message(self, payload, file_path: str, fallback_message: str):
        data = payload.get('data') if isinstance(payload, dict) and isinstance(payload.get('data'), dict) else {}
        original_name = str(data.get('original_name') or os.path.basename(file_path)).strip()
        display_name = original_name or os.path.basename(file_path)
        return success(f'Upload completed: {display_name}')

    def _send_transfer_update(self, transfer_id: str, **payload):
        normalized_transfer_id = str(transfer_id or '').strip()
        if not normalized_transfer_id:
            return

        data = {
            'type': MSG_TYPE_TRANSFER_UPDATE,
            'transfer_id': normalized_transfer_id,
            **payload,
        }
        try:
            self.owner.socket.send(data)
        except Exception:
            # 进度回报失败不能反过来中断实际文件传输。
            pass

    def _send_transfer_failure(self, transfer_id: str, exc: Exception, **payload):
        if isinstance(exc, CommandCancelledError):
            self._send_transfer_update(
                transfer_id,
                state='cancelled',
                stage='cancelled',
                error='',
                **payload,
            )
            return

        self._send_transfer_update(
            transfer_id,
            state='failed',
            stage='failed',
            error=str(exc),
            **payload,
        )

    def _build_progress_callback(self, transfer_id: str, stage: str, filename: str = ''):
        last_report_at = [0.0]
        last_report_bytes = [-1]

        def _callback(transferred_bytes, total_bytes):
            try:
                transferred = max(0, int(transferred_bytes or 0))
            except Exception:
                transferred = 0
            try:
                total = max(0, int(total_bytes or 0))
            except Exception:
                total = 0

            now = time.monotonic()
            is_final = bool(total > 0 and transferred >= total)
            if (
                not is_final
                and last_report_bytes[0] >= 0
                and now - last_report_at[0] < self.PROGRESS_REPORT_INTERVAL_SECONDS
            ):
                return

            last_report_at[0] = now
            last_report_bytes[0] = transferred
            self._send_transfer_update(
                transfer_id,
                state='running',
                stage=stage,
                filename=filename,
                transferred_bytes=transferred,
                total_bytes=total or None,
                progress_supported=True,
            )

        return _callback

    def upload_file_to_server_via_http(
        self,
        file_path: str,
        *,
        artifact_type: str = 'files',
        category: str = 'default',
        extra: dict | None = None,
        progress_callback=None,
    ):
        upload_url = self.client_api.build_file_upload_url()
        strategy = self.get_transfer_strategy()
        form_data = self.build_http_upload_form_data(
            artifact_type=artifact_type,
            category=category,
            extra=extra,
            transfer_buffer_size=strategy.get_buffer_size(),
        )

        return strategy.upload_file(
            file_path,
            upload_url,
            form_data,
            progress_callback=progress_callback,
        )

    def upload_single_file_to_server_result(
        self,
        file_path: str,
        *,
        artifact_type: str = 'files',
        category: str = 'default',
        extra: dict | None = None,
        transfer_id: str = '',
        send_preparing: bool = True,
    ):
        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
        strategy = self.get_transfer_strategy()
        progress_supported = strategy.get_mode_name() != 'legacy'

        self.owner._send_info(self.build_http_upload_start_message(file_path, file_size), 0)

        if transfer_id and send_preparing:
            self._send_transfer_update(
                transfer_id,
                state='running',
                stage='preparing',
                filename=filename,
                total_bytes=file_size,
                transferred_bytes=0,
                progress_supported=progress_supported,
            )

        if transfer_id:
            self._send_transfer_update(
                transfer_id,
                state='running',
                stage='staging',
                filename=filename,
                total_bytes=file_size,
                transferred_bytes=0,
                progress_supported=progress_supported,
            )

        upload_url = self.client_api.build_file_upload_url()
        form_data = self.build_http_upload_form_data(
            artifact_type=artifact_type,
            category=category,
            extra=extra,
            transfer_buffer_size=strategy.get_buffer_size(),
        )
        progress_callback = (
            self._build_progress_callback(transfer_id, 'staging', filename)
            if transfer_id and progress_supported
            else None
        )

        try:
            response = strategy.upload_file(
                file_path,
                upload_url,
                form_data,
                progress_callback=progress_callback,
            )
            response.raise_for_status()

            if transfer_id:
                self._send_transfer_update(
                    transfer_id,
                    state='running',
                    stage='finalizing',
                    filename=filename,
                    total_bytes=file_size,
                    transferred_bytes=file_size,
                    progress_supported=progress_supported,
                )

            payload = self.parse_http_upload_response(response)
            data = payload.get('data') if isinstance(payload, dict) and isinstance(payload.get('data'), dict) else {}
            artifact_id = str(data.get('artifact_id') or '').strip()
            if transfer_id:
                self._send_transfer_update(
                    transfer_id,
                    state='completed',
                    stage='completed',
                    filename=filename,
                    total_bytes=file_size,
                    transferred_bytes=file_size,
                    progress_supported=progress_supported,
                    artifact_id=artifact_id,
                )

            message = self.build_http_upload_success_message(
                payload,
                file_path=file_path,
                fallback_message='HTTP upload completed',
            )
            return 1, message
        except Exception as exc:
            if transfer_id:
                self._send_transfer_failure(
                    transfer_id,
                    exc,
                    filename=filename,
                    total_bytes=file_size,
                    progress_supported=progress_supported,
                )
            raise

    def upload_paths_as_zip_to_server_result(
        self,
        resolved_paths: list[str],
        *,
        archive_name: str = '',
        artifact_type: str = 'files',
        category: str = 'default',
        extra: dict | None = None,
        transfer_id: str = '',
    ):
        if self.archive_service is None:
            raise RuntimeError('archive_service is required')

        temp_archive_path = ''
        try:
            if transfer_id:
                self._send_transfer_update(
                    transfer_id,
                    state='running',
                    stage='preparing',
                    filename=archive_name or f'{len(resolved_paths)} items.zip',
                    transferred_bytes=0,
                    total_bytes=None,
                    progress_supported=True,
                )

            temp_archive_path = self.archive_service.create_zip_from_paths(
                resolved_paths,
                archive_name=archive_name,
            )
            return self.upload_single_file_to_server_result(
                temp_archive_path,
                artifact_type=artifact_type,
                category=category,
                extra=extra,
                transfer_id=transfer_id,
                send_preparing=False,
            )
        except Exception as exc:
            if transfer_id:
                self._send_transfer_failure(
                    transfer_id,
                    exc,
                    filename=(os.path.basename(temp_archive_path) if temp_archive_path else archive_name),
                )
            raise
        finally:
            if temp_archive_path:
                temp_archive_dir = os.path.dirname(temp_archive_path)
                if temp_archive_dir:
                    shutil.rmtree(temp_archive_dir, ignore_errors=True)

    def download_file_from_http(self, url: str, target_path: str, *, transfer_id: str = ''):
        strategy = self.get_transfer_strategy()
        filename = os.path.basename(target_path)
        progress_callback = self._build_progress_callback(
            transfer_id,
            'transferring',
            filename,
        ) if transfer_id else None

        if transfer_id:
            self._send_transfer_update(
                transfer_id,
                state='running',
                stage='transferring',
                filename=filename,
                transferred_bytes=0,
                total_bytes=None,
                progress_supported=True,
            )

        try:
            result = strategy.download_file(
                self.client_api.normalize_file_transfer_url(url),
                target_path,
                progress_callback=progress_callback,
            )
            if transfer_id:
                file_size = os.path.getsize(target_path)
                self._send_transfer_update(
                    transfer_id,
                    state='completed',
                    stage='completed',
                    filename=filename,
                    transferred_bytes=file_size,
                    total_bytes=file_size,
                    progress_supported=True,
                )
            return result
        except Exception as exc:
            if transfer_id:
                self._send_transfer_failure(
                    transfer_id,
                    exc,
                    filename=filename,
                    progress_supported=True,
                )
            raise
