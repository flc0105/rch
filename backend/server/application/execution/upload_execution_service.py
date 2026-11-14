import os

from core.protocol.message_types import MSG_TYPE_TRANSFER_START, MSG_TYPE_TRANSFER_CANCEL
from server.application.command.command_execution_event import CommandExecutionEvent


class UploadExecutionService:
    """
    上传执行服务。

    职责：
    - 负责 server -> client 上传链路的 staging / cleanup
    - 负责构建 Transfer Start 结构化负载
    - 负责把上传执行转换成结构化事件流
    - 浏览器 -> Server 与 Server -> Client 复用同一个 Transfer 生命周期
    """

    def __init__(self, server, command_stream_service, artifact_service=None, transfer_service=None):
        self.server = server
        self.command_stream_service = command_stream_service
        self.artifact_service = artifact_service
        self.transfer_service = transfer_service

    def get_connection(self, target):
        return self.command_stream_service.get_connection(target)

    def _get_artifact_service(self):
        if self.artifact_service is None:
            raise RuntimeError('artifact_service is not available')
        return self.artifact_service

    def _stage_upload(self, local_path: str):
        if not (local_path or '').strip():
            raise ValueError('local_path is required')

        artifact_service = self._get_artifact_service()
        staged_path, safe_name = artifact_service.stage_local_file(
            local_path,
            display_name=os.path.basename(local_path)
        )
        relative_url = artifact_service.build_upload_temp_download_relative_url(staged_path)
        return artifact_service, staged_path, safe_name, relative_url

    @staticmethod
    def _transfer_filename(local_path: str, display_name: str = '') -> str:
        # Staging uses an ASCII safe name; the target filename is user metadata.
        return os.path.basename(str(display_name or local_path).replace('\\', '/')) or 'upload.bin'

    def _cleanup_staged_upload(self, artifact_service, staged_path: str):
        try:
            artifact_service.cleanup_upload_temp_file(staged_path)
        except Exception:
            pass

    def iter_upload_events(
            self,
            target,
            local_path: str,
            *,
            remote_path: str = '',
            display_name: str = '',
            history_entry_id: str = '',
            source: str = 'web',
            task_id: str = '',
            command: str = '',
            tab_id: str = '',
            transfer_id: str = '',
            conflict_policy=None,
    ):
        artifact_service = None
        staged_path = ''
        safe_name = ''
        active_transfer_id = str(transfer_id or '').strip()
        effective_command = (command or f'upload {os.path.basename(local_path)}').strip()

        try:
            artifact_service, staged_path, safe_name, relative_url = self._stage_upload(local_path)
            safe_name = self._transfer_filename(local_path, display_name)
            session = self.get_connection(target)
            client_id = session.session_info.client_id
            staged_size = os.path.getsize(staged_path)
            transfer_metadata = {
                'source': source,
                'task_id': task_id,
                'history_entry_id': history_entry_id,
                'browser_stage': False,
                'transport': 'client_transfer_manager',
            }

            if self.transfer_service is None:
                raise RuntimeError('transfer_service is not available')

            if active_transfer_id:
                updated = self.transfer_service.reset_progress(
                    active_transfer_id,
                    client_id=client_id,
                    tab_id=tab_id,
                    stage='transferring',
                    total_bytes=staged_size,
                    direction='server_to_client',
                    filename=safe_name,
                    hostname=getattr(session.session_info, 'hostname', '') or '',
                    source_path=staged_path,
                    destination_path=remote_path,
                    metadata=transfer_metadata,
                )
                if updated is None:
                    raise ValueError('transfer not found')
                if updated.get('state') != 'running':
                    if updated.get('state') == 'cancelled':
                        payload = {
                            'source': source,
                            'task_id': task_id,
                            'history_entry_id': history_entry_id,
                            'filename': safe_name,
                            'transfer_id': active_transfer_id,
                        }
                        yield CommandExecutionEvent.cancelled('cancelled', payload=payload)
                        yield CommandExecutionEvent.completed(False, payload=payload)
                        return
                    raise RuntimeError(updated.get('error') or 'Transfer is no longer active')
            else:
                transfer = self.transfer_service.create_transfer(
                    client_id=client_id,
                    direction='server_to_client',
                    filename=safe_name,
                    hostname=getattr(session.session_info, 'hostname', '') or '',
                    source_path=staged_path,
                    destination_path=remote_path,
                    tab_id=tab_id,
                    stage='transferring',
                    total_bytes=staged_size,
                    metadata=transfer_metadata,
                )
                active_transfer_id = transfer.get('transfer_id') or ''


            payload = {
                'source': source,
                'task_id': task_id,
                'history_entry_id': history_entry_id,
                'filename': safe_name,
                'transfer_id': active_transfer_id,
            }
            yield CommandExecutionEvent.started(effective_command, payload=payload)
            yield CommandExecutionEvent.progress(
                '',
                payload={**payload, 'stage': 'staged'},
            )

            session.send({
                'type': MSG_TYPE_TRANSFER_START,
                'transfer_id': active_transfer_id,
                'operation': 'server_to_client_file',
                'payload': {
                    'relative_url': relative_url,
                    'filename': safe_name,
                    'save_dir': remote_path,
                    **({'conflict_policy': conflict_policy} if conflict_policy is not None else {}),
                },
            })

            # A cancellation may arrive during staging or before the Client
            # registers the transfer. Reissue it after dispatch if still pending.
            current = self.transfer_service.get_transfer(active_transfer_id) or {}
            foreground = getattr(session, 'get_foreground_task', lambda: None)() or {}
            if (current.get('state') == 'running' and current.get('cancel_supported') is not False and
                    (current.get('stage') == 'cancelling' or
                     (task_id and foreground.get('task_id') == task_id and foreground.get('cancel_requested')))):
                self.transfer_service.mark_cancelling(active_transfer_id)
                session.send({'type': MSG_TYPE_TRANSFER_CANCEL, 'transfer_id': active_transfer_id})

            terminal = self.transfer_service.wait_for_terminal(active_transfer_id)
            if not terminal:
                raise RuntimeError('Transfer disappeared before completion')

            state = str(terminal.get('state') or '').strip().lower()
            if state == 'completed':
                # Transfer progress belongs to the Transfer UI; the command
                # result has one authoritative terminal event (no duplicate
                # success/path/size text in Web Terminal).
                yield CommandExecutionEvent.completed(True, payload=payload)
                return

            if state == 'cancelled':
                yield CommandExecutionEvent.cancelled('cancelled', payload=payload)
                yield CommandExecutionEvent.completed(False, payload=payload)
                return

            yield CommandExecutionEvent.error(
                terminal.get('error') or 'Upload failed',
                payload=payload,
            )
            yield CommandExecutionEvent.completed(False, payload=payload)

        except Exception as exc:
            if active_transfer_id and self.transfer_service is not None:
                current = self.transfer_service.get_transfer(active_transfer_id)
                if current and current.get('state') == 'running':
                    self.transfer_service.fail_transfer(active_transfer_id, str(exc))
            yield CommandExecutionEvent.error(
                str(exc),
                payload={
                    'task_id': task_id,
                    'history_entry_id': history_entry_id,
                    'filename': safe_name,
                    'transfer_id': active_transfer_id,
                },
            )
            yield CommandExecutionEvent.completed(
                False,
                payload={
                    'task_id': task_id,
                    'history_entry_id': history_entry_id,
                    'filename': safe_name,
                    'transfer_id': active_transfer_id,
                },
            )
        finally:
            if artifact_service is not None and staged_path:
                self._cleanup_staged_upload(artifact_service, staged_path)

