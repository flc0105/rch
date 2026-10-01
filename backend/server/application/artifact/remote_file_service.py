import base64
import json

from core.protocol.message_types import MSG_TYPE_TRANSFER_START


class WebRemoteFileService:
    """
    远程文件应用服务。

    当前文件链路：
    - 普通下载：进入 artifact files 区
    - 预览下载：进入 artifact previews 区
    - download / preview 文件搬运统一使用 Client TransferManager
    - artifact_id 通过结构化 transfer_update 回传，不依赖人类命令输出文本

    规则：
    - 所有这里发往 client 且同步等待结果流的前台请求
      统一通过 foreground task 槽保护
    - Remote File Browser 的 download/download-as-zip 例外：文件搬运由 Client TransferManager
      独立执行，不占 command foreground slot；其他同步文件操作仍保持原有 foreground 规则
    """

    def __init__(self, remote_execution_service, artifact_service, transfer_service=None):
        self.remote_execution_service = remote_execution_service
        self.artifact_service = artifact_service
        self.transfer_service = transfer_service

    def _encode_payload_arg(self, payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        encoded = base64.urlsafe_b64encode(raw).decode('utf-8')
        return f'__json__:{encoded}'

    def _build_command(self, name: str, payload: dict | None = None) -> str:
        if not payload:
            return name
        return f'{name} {self._encode_payload_arg(payload)}'

    def browse_directory(
            self,
            client_id: str,
            path: str = '',
            page: int = 1,
            page_size: int = 100,
            show_hidden: bool = False,
            search_keyword: str = '',
            recursive_search: bool = False,
    ) -> dict:
        command = self._build_command('browse_dir', {
            'path': path,
            'page': page,
            'page_size': page_size,
            'show_hidden': show_hidden,
            'search_keyword': search_keyword,
            'recursive_search': recursive_search,
        })
        payload = self.remote_execution_service.run_foreground_json_command(
            client_id,
            command,
            task_type='remote_file',
            source='web_remote_file',
        )

        summary = payload.get('summary') or {}
        pagination = payload.get('pagination') or {}

        return {
            'current_path': payload.get('current_path', ''),
            'parent_path': payload.get('parent_path'),
            'entries': payload.get('entries', []),
            'summary': {
                'total_all': summary.get('total_all', len(payload.get('entries', []) or [])),
                'total_hidden': summary.get('total_hidden', 0),
                'show_hidden': bool(summary.get('show_hidden', show_hidden)),
                'search_keyword': summary.get('search_keyword', search_keyword),
                'recursive_search': bool(summary.get('recursive_search', recursive_search)),
            },
            'pagination': {
                'page': pagination.get('page', page),
                'page_size': pagination.get('page_size', page_size),
                'total_visible': pagination.get('total_visible', len(payload.get('entries', []) or [])),
                'total_pages': pagination.get('total_pages', 1),
                'returned': pagination.get('returned', len(payload.get('entries', []) or [])),
            }
        }

    def delete_path(self, client_id: str, path: str) -> dict:
        if not (path or '').strip():
            raise ValueError('path is required')

        command = self._build_command('delete_path', {'path': path})
        result_text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            command,
            task_type='remote_file',
            source='web_remote_file',
        )

        return {
            'path': path,
            'message': result_text
        }

    def create_directory(self, client_id: str, path: str) -> dict:
        if not (path or '').strip():
            raise ValueError('path is required')

        command = self._build_command('mkdir_path', {'path': path})
        result_text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            command,
            task_type='remote_file',
            source='web_remote_file',
        )

        return {
            'path': path,
            'message': result_text
        }

    def rename_path(self, client_id: str, old_path: str, new_name: str) -> dict:
        if not (old_path or '').strip():
            raise ValueError('old_path is required')
        if not (new_name or '').strip():
            raise ValueError('new_name is required')

        command = self._build_command('rename_path', {
            'old_path': old_path,
            'new_name': new_name
        })
        result_text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            command,
            task_type='remote_file',
            source='web_remote_file',
        )

        return {
            'old_path': old_path,
            'new_name': new_name,
            'message': result_text
        }

    def _start_client_transfer(self, session, transfer_id: str, operation: str, payload: dict):
        session.send({
            'type': MSG_TYPE_TRANSFER_START,
            'transfer_id': str(transfer_id or '').strip(),
            'operation': str(operation or '').strip(),
            'payload': dict(payload or {}),
        })

    def _wait_for_transfer_artifact(self, transfer_id: str) -> tuple[dict, dict]:
        if self.transfer_service is None:
            raise RuntimeError('transfer_service is not available')

        terminal = self.transfer_service.wait_for_terminal(transfer_id)
        if not terminal:
            raise RuntimeError('Transfer disappeared before completion')

        state = str(terminal.get('state') or '').strip().lower()
        if state == 'cancelled':
            raise RuntimeError('Transfer cancelled')
        if state != 'completed':
            raise RuntimeError(terminal.get('error') or 'Remote file transfer failed')

        artifact_id = str(terminal.get('artifact_id') or '').strip()
        if not artifact_id:
            raise RuntimeError('Remote file transfer completed, but artifact_id is missing')

        artifact = self.artifact_service.get_artifact_by_id(artifact_id)
        if not isinstance(artifact, dict) or not artifact.get('artifact_id'):
            raise RuntimeError('Artifact was not found after HTTP upload completed')
        return terminal, artifact

    def download_file(self, client_id: str, path: str, history_entry_id: str = '', tab_id: str = '') -> dict:
        if not (path or '').strip():
            raise ValueError('path is required')
        if self.transfer_service is None:
            raise RuntimeError('transfer_service is not available')

        normalized_path = path.strip()
        session = self.remote_execution_service.get_connection(client_id)
        hostname = getattr(session.session_info, 'hostname', '') or ''
        transfer = self.transfer_service.create_transfer(
            client_id=client_id,
            direction='client_to_server',
            filename=normalized_path.replace('\\', '/').rstrip('/').split('/')[-1],
            hostname=hostname,
            source_path=normalized_path,
            destination_path='Artifacts',
            tab_id=tab_id,
            stage='preparing',
            metadata={
                'source': 'remote_file_download',
                'transport': 'client_transfer_manager',
            },
        )
        transfer_id = transfer.get('transfer_id') or ''

        try:
            self._start_client_transfer(
                session,
                transfer_id,
                'client_to_server_file',
                {
                    'path': normalized_path,
                    'artifact_type': 'files',
                    'category': 'download',
                },
            )
            _, artifact = self._wait_for_transfer_artifact(transfer_id)
            return {
                'path': normalized_path,
                'message': 'Remote file transfer completed',
                'artifact': artifact,
                'transfer_id': transfer_id,
            }
        except Exception as exc:
            current = self.transfer_service.get_transfer(transfer_id)
            if current and current.get('state') == 'running':
                self.transfer_service.fail_transfer(transfer_id, str(exc), client_id=client_id)
            raise

    def download_paths_as_zip(
            self,
            client_id: str,
            paths: list[str],
            archive_name: str = '',
            history_entry_id: str = '',
            tab_id: str = '',
    ) -> dict:
        if not isinstance(paths, list) or not paths:
            raise ValueError('paths is required')
        if self.transfer_service is None:
            raise RuntimeError('transfer_service is not available')

        normalized_paths = [
            str(item or '').strip()
            for item in paths
            if str(item or '').strip()
        ]
        if not normalized_paths:
            raise ValueError('paths is required')

        session = self.remote_execution_service.get_connection(client_id)
        hostname = getattr(session.session_info, 'hostname', '') or ''
        transfer = self.transfer_service.create_transfer(
            client_id=client_id,
            direction='client_to_server',
            filename=archive_name or f'{len(normalized_paths)} items.zip',
            hostname=hostname,
            source_path=normalized_paths[0] if len(normalized_paths) == 1 else f'{len(normalized_paths)} selected paths',
            destination_path='Artifacts',
            tab_id=tab_id,
            stage='preparing',
            metadata={
                'source': 'remote_file_download_zip',
                'source_count': len(normalized_paths),
                'transport': 'client_transfer_manager',
            },
        )
        transfer_id = transfer.get('transfer_id') or ''

        try:
            self._start_client_transfer(
                session,
                transfer_id,
                'client_to_server_zip',
                {
                    'paths': normalized_paths,
                    'archive_name': archive_name,
                    'artifact_type': 'files',
                    'category': 'bundle',
                },
            )
            _, artifact = self._wait_for_transfer_artifact(transfer_id)
            return {
                'paths': normalized_paths,
                'message': 'Remote ZIP transfer completed',
                'artifact': artifact,
                'transfer_id': transfer_id,
            }
        except Exception as exc:
            current = self.transfer_service.get_transfer(transfer_id)
            if current and current.get('state') == 'running':
                self.transfer_service.fail_transfer(transfer_id, str(exc), client_id=client_id)
            raise

    def create_zip_from_paths(
            self,
            client_id: str,
            paths: list[str],
            destination_dir: str,
            archive_name: str = '',
    ) -> dict:
        if not isinstance(paths, list) or not paths:
            raise ValueError('paths is required')
        if not (destination_dir or '').strip():
            raise ValueError('destination_dir is required')

        normalized_paths = [
            str(item or '').strip()
            for item in paths
            if str(item or '').strip()
        ]
        if not normalized_paths:
            raise ValueError('paths is required')

        return self.remote_execution_service.run_foreground_json_command(
            client_id,
            self._build_command('create_zip_paths', {
                'paths': normalized_paths,
                'destination_dir': destination_dir.strip(),
                'archive_name': str(archive_name or '').strip(),
            }),
            task_type='remote_file',
            source='web_remote_file',
        )

    def peek_zip(self, client_id: str, path: str) -> dict:
        if not (path or '').strip():
            raise ValueError('path is required')

        return self.remote_execution_service.run_foreground_json_command(
            client_id,
            self._build_command('peek_zip', {'path': path.strip()}),
            task_type='remote_file',
            source='web_remote_file',
        )

    def read_zip_entry(self, client_id: str, path: str, entry_name: str) -> dict:
        if not (path or '').strip():
            raise ValueError('path is required')
        if not (entry_name or '').strip():
            raise ValueError('entry_name is required')

        return self.remote_execution_service.run_foreground_json_command(
            client_id,
            self._build_command('read_zip_entry', {
                'path': path.strip(),
                'entry_name': entry_name,
            }),
            task_type='remote_file',
            source='web_remote_file',
        )

    def extract_zip(self, client_id: str, path: str, destination_dir: str) -> dict:
        if not (path or '').strip():
            raise ValueError('path is required')
        if not (destination_dir or '').strip():
            raise ValueError('destination_dir is required')

        return self.remote_execution_service.run_foreground_json_command(
            client_id,
            self._build_command('extract_zip_path', {
                'path': path.strip(),
                'destination_dir': destination_dir.strip(),
            }),
            task_type='remote_file',
            source='web_remote_file',
        )

    def delete_paths(self, client_id: str, paths: list[str]) -> dict:
        """
        批量删除远程文件或目录
        """
        if not isinstance(paths, list) or not paths:
            raise ValueError('paths is required and must be a non-empty list')

        normalized_paths = [
            str(item or '').strip()
            for item in paths
            if str(item or '').strip()
        ]
        if not normalized_paths:
            raise ValueError('paths is required and must contain valid paths')

        command = self._build_command('delete_paths', {'paths': normalized_paths})
        result_text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            command,
            task_type='remote_file',
            source='web_remote_file',
        )

        return {
            'paths': normalized_paths,
            'message': result_text
        }

    def paste_paths(self, client_id: str, paths: list[str], destination_dir: str, operation: str = 'copy') -> dict:
        if not isinstance(paths, list) or not paths:
            raise ValueError('paths is required and must be a non-empty list')
        if not (destination_dir or '').strip():
            raise ValueError('destination_dir is required')

        normalized_paths = [
            str(item or '').strip()
            for item in paths
            if str(item or '').strip()
        ]
        if not normalized_paths:
            raise ValueError('paths is required and must contain valid paths')

        normalized_destination_dir = destination_dir.strip()
        normalized_operation = str(operation or 'copy').strip().lower()
        if normalized_operation not in ('copy', 'move'):
            raise ValueError('operation must be copy or move')

        command = self._build_command('paste_paths', {
            'paths': normalized_paths,
            'destination_dir': normalized_destination_dir,
            'operation': normalized_operation,
        })
        result_text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            command,
            task_type='remote_file',
            source='web_remote_file',
        )

        return {
            'paths': normalized_paths,
            'destination_dir': normalized_destination_dir,
            'operation': normalized_operation,
            'message': result_text,
        }

    def preview_file(
            self,
            client_id: str,
            path: str,
            history_entry_id: str = '',
            tab_id: str = '',
    ) -> dict:
        if not (path or '').strip():
            raise ValueError('path is required')
        if self.transfer_service is None:
            raise RuntimeError('transfer_service is not available')

        normalized_path = path.strip()
        session = self.remote_execution_service.get_connection(client_id)
        hostname = getattr(session.session_info, 'hostname', '') or ''
        filename = normalized_path.replace('\\', '/').rstrip('/').split('/')[-1]
        transfer = self.transfer_service.create_transfer(
            client_id=client_id,
            direction='client_to_server',
            filename=filename,
            hostname=hostname,
            source_path=normalized_path,
            destination_path='Artifacts / Previews',
            tab_id=tab_id,
            stage='preparing',
            metadata={
                'source': 'remote_file_preview',
                'transport': 'client_transfer_manager',
            },
        )
        transfer_id = transfer.get('transfer_id') or ''

        try:
            self._start_client_transfer(
                session,
                transfer_id,
                'client_to_server_preview',
                {'path': normalized_path},
            )
            _, artifact = self._wait_for_transfer_artifact(transfer_id)
            return self.artifact_service.build_preview_payload(artifact.get('artifact_id', ''))
        except Exception as exc:
            current = self.transfer_service.get_transfer(transfer_id)
            if current and current.get('state') == 'running':
                self.transfer_service.fail_transfer(transfer_id, str(exc), client_id=client_id)
            raise

    def save_file_content(self, client_id: str, path: str, content: str, encoding: str = 'utf-8') -> dict:
        """
        保存内容到远程文件
        """
        if not (path or '').strip():
            raise ValueError('path is required')

        normalized_path = path.strip()

        # 构建保存命令
        command = self._build_command('save_file_content', {
            'path': normalized_path,
            'content': content,
            'encoding': encoding
        })

        result_text = self.remote_execution_service.run_foreground_text_command(
            client_id,
            command,
            task_type='remote_file',
            source='web_remote_file',
        )

        return {
            'path': normalized_path,
            'message': result_text
        }

    def get_file_content(self, client_id: str, path: str) -> dict:
        """
        获取远程文件内容用于编辑
        """
        if not (path or '').strip():
            raise ValueError('path is required')

        # 使用现有的预览功能获取内容
        preview_result = self.preview_file(client_id, path)

        # 从预览结果中提取内容
        if preview_result.get('type') == 'text':
            return {
                'path': path,
                'content': preview_result.get('content', ''),
                'truncated': preview_result.get('truncated', False),
                'name': preview_result.get('name', ''),
                'size': len(preview_result.get('content', ''))
            }
        else:
            raise ValueError('File is not a text file or cannot be edited')
