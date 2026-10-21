import os

from core.protocol.message_types import MSG_TYPE_TRANSFER_START
from core.utils.output_marker import success
from server.application.command.command_types import COMMAND_TYPE_COMMAND
from server.application.command.command_execution_event import CommandExecutionEvent


class UploadExecutionService:
    """
    上传执行服务。

    职责：
    - 负责 server -> client 上传链路的 staging / cleanup
    - 负责构建 receive_file 命令负载
    - 负责把上传执行转换成结构化事件流
    - 浏览器 -> Server 与 Server -> Client 复用同一个 Transfer 生命周期
    """

    def __init__(self, server, command_stream_service, artifact_service=None, transfer_service=None):
        self.server = server
        self.command_stream_service = command_stream_service
        self.artifact_service = artifact_service
        self.transfer_service = transfer_service

    def _record_cli_upload(self, session, transfer_id, history_entry_id, source, filename, local_path):
        if source != 'cli' or not history_entry_id or not transfer_id or self.transfer_service is None:
            return
        recorder = getattr(self.transfer_service, 'activity_recorder', None)
        orchestrator = getattr(self.server, 'command_history_orchestrator', None)
        if recorder is None or orchestrator is None:
            return
        claimed = orchestrator.claim_upload_intent(session, history_entry_id)
        if claimed:
            origin, original_input = claimed
            recorder.track(transfer_id, session, activity_id=history_entry_id,
                           action='upload_files', origin=origin,
                           arguments={'input': original_input,
                                      'filename': filename, 'count': 1, 'source': 'cli'})

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

    def _cleanup_staged_upload(self, artifact_service, staged_path: str):
        try:
            artifact_service.cleanup_upload_temp_file(staged_path)
        except Exception:
            pass

    def _iter_transfer_manager_upload_events(
            self,
            target,
            local_path: str,
            *,
            remote_path: str = '',
            history_entry_id: str = '',
            source: str = 'web',
            task_id: str = '',
            command: str = '',
            tab_id: str = '',
            transfer_id: str = '',
    ):
        artifact_service = None
        staged_path = ''
        safe_name = ''
        active_transfer_id = str(transfer_id or '').strip()
        effective_command = (command or f'upload {os.path.basename(local_path)}').strip()

        try:
            artifact_service, staged_path, safe_name, relative_url = self._stage_upload(local_path)
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

            self._record_cli_upload(session, active_transfer_id, history_entry_id, source, safe_name, local_path)

            payload = {
                'source': source,
                'task_id': task_id,
                'history_entry_id': history_entry_id,
                'filename': safe_name,
                'transfer_id': active_transfer_id,
            }
            yield CommandExecutionEvent.started(effective_command, payload=payload)
            yield CommandExecutionEvent.progress(
                success(f'Staged upload file: {safe_name}'),
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
                },
            })

            terminal = self.transfer_service.wait_for_terminal(active_transfer_id)
            if not terminal:
                raise RuntimeError('Transfer disappeared before completion')

            state = str(terminal.get('state') or '').strip().lower()
            if state == 'completed':
                yield CommandExecutionEvent.chunk(
                    1,
                    success(f'File transferred successfully: {safe_name}'),
                    payload=payload,
                )
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

    def iter_upload_events(
            self,
            target,
            local_path: str,
            *,
            remote_path: str = '',
            history_entry_id: str = '',
            build_http_receive_command,
            source: str = 'web',
            task_id: str = '',
            command: str = '',
            tab_id: str = '',
            transfer_id: str = '',
            use_transfer_manager: bool = False,
    ):
        """
        执行上传事件流。

        对外统一产出：
        - started
        - progress
        - chunk
        - error
        - completed
        """
        if use_transfer_manager:
            yield from self._iter_transfer_manager_upload_events(
                target,
                local_path,
                remote_path=remote_path,
                history_entry_id=history_entry_id,
                source=source,
                task_id=task_id,
                command=command,
                tab_id=tab_id,
                transfer_id=transfer_id,
            )
            return

        artifact_service = None
        staged_path = ''
        safe_name = ''
        active_transfer_id = str(transfer_id or '').strip()
        ok = True
        last_error = ''

        effective_command = (command or f'upload {os.path.basename(local_path)}').strip()

        try:
            artifact_service, staged_path, safe_name, relative_url = self._stage_upload(local_path)
            session = self.get_connection(target)
            client_id = session.session_info.client_id
            staged_size = os.path.getsize(staged_path)
            transfer_metadata = {
                'source': source,
                'task_id': task_id,
                'history_entry_id': history_entry_id,
                'browser_stage': False,
            }

            if self.transfer_service is not None:
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

                self._record_cli_upload(session, active_transfer_id, history_entry_id, source, safe_name, local_path)

            yield CommandExecutionEvent.started(
                effective_command,
                payload={
                    'source': source,
                    'task_id': task_id,
                    'history_entry_id': history_entry_id,
                    'filename': safe_name,
                    'transfer_id': active_transfer_id,
                },
            )

            yield CommandExecutionEvent.progress(
                success(f'Staged upload file: {safe_name}'),
                payload={
                    'stage': 'staged',
                    'task_id': task_id,
                    'history_entry_id': history_entry_id,
                    'filename': safe_name,
                    'transfer_id': active_transfer_id,
                },
            )

            command_text = build_http_receive_command({
                'relative_url': relative_url,
                'filename': safe_name,
                'save_dir': remote_path,
                'transfer_id': active_transfer_id,
            })

            result_iter = self.command_stream_service.stream_command(
                session,
                command_text,
                command_type=COMMAND_TYPE_COMMAND,
                extra=None,
                history_entry_id=history_entry_id,
            )

            for status, result in result_iter:
                text = '' if result is None else str(result)

                if int(status or 0) == 0:
                    ok = False
                    last_error = text
                    yield CommandExecutionEvent.error(
                        text,
                        payload={
                            'task_id': task_id,
                            'history_entry_id': history_entry_id,
                            'filename': safe_name,
                            'transfer_id': active_transfer_id,
                        },
                    )
                else:
                    yield CommandExecutionEvent.chunk(
                        int(status),
                        text,
                        payload={
                            'task_id': task_id,
                            'history_entry_id': history_entry_id,
                            'filename': safe_name,
                            'transfer_id': active_transfer_id,
                        },
                    )

        except Exception as exc:
            ok = False
            last_error = str(exc)
            if active_transfer_id and self.transfer_service is not None:
                self.transfer_service.fail_transfer(active_transfer_id, last_error)
            yield CommandExecutionEvent.error(
                str(exc),
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

        if active_transfer_id and self.transfer_service is not None:
            if ok:
                self.transfer_service.complete_transfer(active_transfer_id)
            else:
                self.transfer_service.fail_transfer(active_transfer_id, last_error or 'Upload failed')

        yield CommandExecutionEvent.completed(
            ok,
            payload={
                'task_id': task_id,
                'history_entry_id': history_entry_id,
                'filename': safe_name,
                'transfer_id': active_transfer_id,
            },
        )
