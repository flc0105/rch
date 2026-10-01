import os
import threading

from client.commands.base import CommandRuntimeMixin
from client.commands.common.services.filesystem.archive_service import ArchiveService
from client.commands.common.services.filesystem.path_resolver import PathResolver
from client.commands.common.services.filesystem.preview_image_service import PreviewImageService
from client.commands.common.services.transfer.http_file_transfer_service import CommandHttpFileTransferService
from client.commands.runtime.context import CommandCancelledError, CommandExecutionContext
from client.config import runtime_config
from client.http.client_api import ClientApiClient
from core.protocol.message_types import MSG_TYPE_TRANSFER_UPDATE


class _TransferTaskOwner(CommandRuntimeMixin):
    """
    为独立 Transfer worker 复用现有 HTTP/Archive 服务提供最小运行上下文。

    它不绑定 command_id，也不进入 command foreground slot；取消与 cleanup 由独立
    CommandExecutionContext 承载，这样现有 cancelable HTTP strategy 可以直接复用。
    """

    def __init__(self, connection, execution_context: CommandExecutionContext):
        self.socket = connection
        self.command_id = None
        self.execution_context = execution_context
        self.HTTP_TRANSFER_MODE = runtime_config.HTTP_TRANSFER_MODE

        self._path_resolver = PathResolver(iter_interruptible=self._iter_interruptible)
        self._archive_service = ArchiveService(
            path_resolver=self._path_resolver,
            ensure_not_interrupted=self._ensure_not_interrupted,
            iter_interruptible=self._iter_interruptible,
        )
        self._client_api = ClientApiClient()
        self._preview_image_service = PreviewImageService()

    @property
    def path_resolver(self):
        return self._path_resolver

    @property
    def archive_service(self):
        return self._archive_service

    @property
    def client_api(self):
        return self._client_api

    @property
    def preview_image_service(self):
        return self._preview_image_service

    def _send_info(self, _result, _eof=0):
        # 独立 Transfer 没有 command result stream；实时状态统一走 transfer_update。
        return None

    def _resolve_command_fallback_timeout(self, fallback_timeout=None):
        # Transfer 不继承 COMMAND_DEFAULT_TIMEOUT；文件传输只使用自己的 idle timeout。
        return fallback_timeout


class ClientTransferManager:
    """
    Client 端独立文件传输任务管理器。

    只承载由 Server 明确下发的 Web/Transfer Center 文件搬运任务，不替代现有
    upload/download CLI 命令入口。这样 Web 大文件不再占 command foreground slot，
    而原有 CLI 行为保持不变。
    """

    OP_CLIENT_TO_SERVER_FILE = 'client_to_server_file'
    OP_CLIENT_TO_SERVER_PREVIEW = 'client_to_server_preview'
    OP_CLIENT_TO_SERVER_ZIP = 'client_to_server_zip'
    OP_SERVER_TO_CLIENT_FILE = 'server_to_client_file'

    SUPPORTED_OPERATIONS = {
        OP_CLIENT_TO_SERVER_FILE,
        OP_CLIENT_TO_SERVER_PREVIEW,
        OP_CLIENT_TO_SERVER_ZIP,
        OP_SERVER_TO_CLIENT_FILE,
    }

    def __init__(self, connection):
        self.connection = connection
        self._lock = threading.RLock()
        self._tasks = {}

    def start_transfer(self, transfer_id: str, operation: str, payload=None):
        normalized_id = str(transfer_id or '').strip()
        normalized_operation = str(operation or '').strip()
        if not normalized_id:
            return

        if normalized_operation not in self.SUPPORTED_OPERATIONS:
            self._send_update(
                normalized_id,
                state='failed',
                stage='failed',
                error=f'Unsupported transfer operation: {normalized_operation or "empty"}',
            )
            return

        with self._lock:
            existing = self._tasks.get(normalized_id)
            if existing and existing.get('worker') and existing['worker'].is_alive():
                return

            context = CommandExecutionContext(command_id=0, timeout=None)
            owner = _TransferTaskOwner(self.connection, context)
            item = {
                'transfer_id': normalized_id,
                'operation': normalized_operation,
                'payload': dict(payload or {}),
                'context': context,
                'owner': owner,
            }
            worker = threading.Thread(
                target=self._run_transfer,
                args=(item,),
                daemon=True,
                name=f'transfer-{normalized_id[:8]}',
            )
            item['worker'] = worker
            self._tasks[normalized_id] = item

        worker.start()

    def cancel_transfer(self, transfer_id: str) -> dict:
        normalized_id = str(transfer_id or '').strip()
        with self._lock:
            item = self._tasks.get(normalized_id)
            if not item:
                return {
                    'accepted': False,
                    'message': 'Transfer is not active on this client',
                }
            context = item.get('context')

        if context is None:
            return {
                'accepted': False,
                'message': 'Transfer cancellation context is unavailable',
            }

        result = context.request_cancel()
        if result.get('accepted'):
            # 这里只表示取消请求已被 worker 接收；真正停止后由 worker 回报 cancelled。
            self._send_update(
                normalized_id,
                state='running',
                stage='cancelling',
                error='',
            )
        return result

    def cancel_all(self, notify: bool = False):
        with self._lock:
            items = list(self._tasks.values())

        for item in items:
            context = item.get('context')
            if context is None:
                continue
            result = context.request_cancel()
            if notify and result.get('accepted'):
                self._send_update(
                    item.get('transfer_id') or '',
                    state='running',
                    stage='cancelling',
                    error='',
                )

    def _run_transfer(self, item: dict):
        transfer_id = item['transfer_id']
        operation = item['operation']
        payload = item['payload']
        owner = item['owner']
        context = item['context']
        service = CommandHttpFileTransferService(
            owner,
            archive_service=owner.archive_service,
            client_api=owner.client_api,
        )

        try:
            strategy = service.get_transfer_strategy()
            self._send_update(
                transfer_id,
                state='running',
                cancel_supported=bool(strategy.is_cancel_supported()),
            )

            if operation == self.OP_CLIENT_TO_SERVER_FILE:
                self._run_client_to_server_file(service, owner, transfer_id, payload)
            elif operation == self.OP_CLIENT_TO_SERVER_PREVIEW:
                self._run_client_to_server_preview(service, owner, transfer_id, payload)
            elif operation == self.OP_CLIENT_TO_SERVER_ZIP:
                self._run_client_to_server_zip(service, owner, transfer_id, payload)
            elif operation == self.OP_SERVER_TO_CLIENT_FILE:
                self._run_server_to_client_file(service, owner, transfer_id, payload)

        except CommandCancelledError:
            self._send_update(
                transfer_id,
                state='cancelled',
                stage='cancelled',
                error='',
            )
        except Exception as exc:
            self._send_update(
                transfer_id,
                state='failed',
                stage='failed',
                error=str(exc),
            )
        finally:
            try:
                context.run_cleanup()
            except Exception:
                pass
            with self._lock:
                current = self._tasks.get(transfer_id)
                if current is item:
                    self._tasks.pop(transfer_id, None)

    def _run_client_to_server_file(self, service, owner, transfer_id: str, payload: dict):
        source_path = owner.path_resolver.require_existing_file_from_arg(payload.get('path') or '')
        service.upload_single_file_to_server_result(
            source_path,
            artifact_type=str(payload.get('artifact_type') or 'files'),
            category=str(payload.get('category') or 'download'),
            extra=payload.get('extra') if isinstance(payload.get('extra'), dict) else None,
            transfer_id=transfer_id,
        )

    def _run_client_to_server_preview(self, service, owner, transfer_id: str, payload: dict):
        source_path = owner.path_resolver.require_existing_file_from_arg(payload.get('path') or '')
        prepared_file = owner.preview_image_service.prepare_upload_file(source_path)
        try:
            service.upload_single_file_to_server_result(
                prepared_file.upload_path,
                artifact_type='previews',
                category='preview_cache',
                extra=prepared_file.extra,
                transfer_id=transfer_id,
            )
        finally:
            owner.preview_image_service.cleanup_upload_file(prepared_file)

    def _run_client_to_server_zip(self, service, owner, transfer_id: str, payload: dict):
        raw_paths = payload.get('paths') or []
        if not isinstance(raw_paths, list) or not raw_paths:
            raise ValueError('paths is required')

        resolved_paths = owner.path_resolver.require_existing_paths_from_list(raw_paths)
        service.upload_paths_as_zip_to_server_result(
            resolved_paths,
            archive_name=str(payload.get('archive_name') or '').strip(),
            artifact_type=str(payload.get('artifact_type') or 'files'),
            category=str(payload.get('category') or 'bundle'),
            extra=payload.get('extra') if isinstance(payload.get('extra'), dict) else None,
            transfer_id=transfer_id,
        )

    def _run_server_to_client_file(self, service, owner, transfer_id: str, payload: dict):
        relative_url = str(payload.get('relative_url') or '').strip()
        url = str(payload.get('url') or '').strip()
        filename = str(payload.get('filename') or '').strip()
        save_dir = str(payload.get('save_dir') or '').strip()

        if not url:
            if not relative_url:
                raise ValueError('url or relative_url is required')
            url = owner.client_api.normalize_file_transfer_url(relative_url)
        else:
            url = owner.client_api.normalize_file_transfer_url(url)

        if not filename:
            raise ValueError('filename is required')

        target_dir = owner.path_resolver.resolve_target_path(save_dir or '.')
        if os.path.exists(target_dir) and not os.path.isdir(target_dir):
            raise NotADirectoryError(f'Target path is not a directory: {target_dir}')

        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, os.path.basename(filename))

        try:
            service.download_file_from_http(
                url,
                target_path,
                transfer_id=transfer_id,
            )
        except Exception:
            if context_cancelled(owner.execution_context):
                try:
                    if os.path.isfile(target_path):
                        os.remove(target_path)
                except Exception:
                    pass
            raise

    def _send_update(self, transfer_id: str, **payload):
        normalized_id = str(transfer_id or '').strip()
        if not normalized_id:
            return
        try:
            self.connection.send({
                'type': MSG_TYPE_TRANSFER_UPDATE,
                'transfer_id': normalized_id,
                **payload,
            })
        except Exception:
            pass


def context_cancelled(context: CommandExecutionContext | None) -> bool:
    return bool(context and context.is_cancel_requested())
