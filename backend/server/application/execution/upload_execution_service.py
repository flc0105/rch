import os
import threading
from collections import deque
from dataclasses import dataclass

from core.protocol.message_types import MSG_TYPE_TRANSFER_START, MSG_TYPE_TRANSFER_CANCEL
from server.application.command.command_execution_event import CommandExecutionEvent


@dataclass(frozen=True)
class StagedUpload:
    transfer_id: str
    local_path: str
    display_name: str
    remote_path: str
    conflict_policy: str | None


class UploadExecutionService:
    """
    上传执行服务。

    职责：
    - 负责 server -> client 上传链路的 staging / cleanup
    - 负责构建 Transfer Start 结构化负载
    - 负责把上传执行转换成结构化事件流
    - 浏览器 -> Server 与 Server -> Client 复用同一个 Transfer 生命周期
    """

    REMOTE_UPLOAD_LABEL = '[Remote Upload]'

    @classmethod
    def format_display_command(cls, filename: str) -> str:
        return f'{cls.REMOTE_UPLOAD_LABEL} {filename}'

    def __init__(self, server, command_stream_service, artifact_service=None, transfer_service=None):
        self.server = server
        self.command_stream_service = command_stream_service
        self.artifact_service = artifact_service
        self.transfer_service = transfer_service
        self._batch_changed = threading.Condition()
        self._batch_queues = {}

    def open_browser_batch(self, batch_id):
        with self._batch_changed:
            if batch_id in self._batch_queues:
                raise ValueError('Upload batch already scheduled')
            self._batch_queues[batch_id] = deque()

    def close_browser_batch(self, batch_id):
        with self._batch_changed:
            pending = self._batch_queues.pop(batch_id, ())
            self._batch_changed.notify_all()
        for item in pending:
            self._get_artifact_service().cleanup_upload_temp_file(item.local_path)

    def enqueue_browser_upload(self, batch_id, target, local_path, *, display_name,
                               remote_path, tab_id, transfer_id, conflict_policy):
        session = self.get_connection(target)
        item = StagedUpload(transfer_id, local_path, display_name, remote_path, conflict_policy)
        with self._batch_changed:
            while True:
                pending = self._batch_queues.get(batch_id)
                transfer = self.transfer_service.get_transfer(transfer_id, tab_id=tab_id)
                if (pending is None or not transfer or transfer['state'] != 'running'
                        or transfer.get('batch_id') != batch_id
                        or transfer.get('client_id') != session.session_info.client_id):
                    raise ValueError('Upload batch member is no longer active')
                # The parent owns one Client transfer at a time and one queued file.
                # The browser content request applies backpressure when that slot is full.
                if not pending:
                    pending.append(item)
                    self._batch_changed.notify_all()
                    return {'transfer_id': transfer_id, 'client_id': session.session_info.client_id}
                self._batch_changed.wait(1)

    def iter_upload_operation(self, target, local_path='', *, batch_id='', **options):
        if not batch_id:
            yield from self.iter_upload_events(target, local_path, **options)
            return
        task_id = options.get('task_id', '')
        tab_id = options.get('tab_id', '')
        self.transfer_service.bind_batch_task(batch_id, task_id)
        try:
            yield CommandExecutionEvent.started(options.get('command', ''))
            while True:
                batch = self.transfer_service.get_batch(batch_id)
                if not batch:
                    raise RuntimeError('Upload batch disappeared')
                if batch['state'] != 'running':
                    if batch['state'] == 'cancelled':
                        yield CommandExecutionEvent.cancelled('cancelled')
                    elif batch['state'] != 'completed':
                        yield CommandExecutionEvent.error(batch['error'] or 'One or more files failed')
                    yield CommandExecutionEvent.completed(batch['state'] == 'completed')
                    return
                with self._batch_changed:
                    pending = self._batch_queues.get(batch_id)
                    if pending is None:
                        raise RuntimeError('Upload batch scheduler is closed')
                    item = pending.popleft() if pending else None
                    self._batch_changed.notify_all()
                    if item is None:
                        self._batch_changed.wait(1)
                if item is None:
                    self.transfer_service.expire_idle_batch(batch_id)
                    continue
                current = self.transfer_service.get_transfer(item.transfer_id, tab_id=tab_id)
                if not current or current['state'] != 'running':
                    self._get_artifact_service().cleanup_upload_temp_file(item.local_path)
                    continue
                try:
                    # Individual files use the same upload event generator as a single upload.
                    # Their lifecycle belongs to Transfer Center; the enclosing operation owns
                    # the Web Task's final result and Activity.
                    for _ in self.iter_upload_events(
                            target, item.local_path, display_name=item.display_name,
                            remote_path=item.remote_path, transfer_id=item.transfer_id,
                            conflict_policy=item.conflict_policy, tab_id=tab_id,
                            task_id=task_id, history_entry_id=options.get('history_entry_id', ''),
                            source=options.get('source', 'web')):
                        pass
                except Exception:
                    self._get_artifact_service().cleanup_upload_temp_file(item.local_path)
                    raise
        except Exception as exc:
            batch = self.transfer_service.get_batch(batch_id)
            if batch and batch['state'] == 'running':
                self.transfer_service.finalize_batch(batch_id=batch_id, client_id=batch['client_id'],
                    tab_id=batch['tab_id'], folder_count=batch['folder_count'], error=str(exc))
                for member in self.transfer_service.list_batch_members(batch_id):
                    if member['state'] == 'running':
                        self.transfer_service.fail_transfer(member['transfer_id'], str(exc))
            raise
        finally:
            self.close_browser_batch(batch_id)

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
        if artifact_service.is_upload_temp_file(local_path):
            staged_path, safe_name = local_path, os.path.basename(local_path)
        else:
            staged_path, safe_name = artifact_service.stage_local_file(
                local_path, display_name=os.path.basename(local_path))
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
        effective_command = (command or self.format_display_command(self._transfer_filename(local_path, display_name))).strip()

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

            terminal = self.transfer_service.wait_for_terminal_or_idle(active_transfer_id)
            if terminal and terminal.get('state') == 'running':
                # Ask the Client to stop before releasing its staging file. No completion
                # claim is made if the peer stopped reporting its actual outcome.
                try:
                    session.send({'type': MSG_TYPE_TRANSFER_CANCEL, 'transfer_id': active_transfer_id})
                finally:
                    self.transfer_service.fail_transfer(active_transfer_id, 'Transfer progress timed out; check destination before retrying')
                terminal = self.transfer_service.get_transfer(active_transfer_id)
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
            elif self.artifact_service is not None:
                self._cleanup_staged_upload(self.artifact_service, local_path)

