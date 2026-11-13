import os

from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


class RemoteFilesManager:
    """Structured remote file operations; one scope per request."""

    def execute(self, scope, action, payload):
        handler = self.actions.get(action)
        if handler is None:
            return 0, f'Unsupported remote_files Control action: {action}'
        return handler(scope, payload)

    @property
    def actions(self):
        return {
            'browse_directory': self.browse_directory,
            'create_directory': self.create_directory,
            'rename_path': self.rename_path,
            'delete_paths': self.delete_paths,
            'paste_paths': self.paste_paths,
            'create_archive': self.create_archive,
            'peek_archive': self.peek_archive,
            'read_archive_entry': self.read_archive_entry,
            'extract_archive': self.extract_archive,
            'inspect_upload': self.inspect_upload,
            'save_file': self.save_file,
        }

    def create_archive(self, scope, payload):
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid ZIP payload'

            raw_paths = payload.get('paths') or []
            destination_dir = str(payload.get('destination_dir') or '').strip()
            archive_name = str(payload.get('archive_name') or '').strip()

            if not isinstance(raw_paths, list) or not raw_paths:
                return 0, 'paths is required'
            if not destination_dir:
                return 0, 'destination_dir is required'

            resolved_paths = scope.path_resolver.require_existing_paths_from_list(raw_paths)
            resolved_destination = scope.path_resolver.require_existing_directory(destination_dir)
            archive_path = scope.archive_service.create_zip_in_directory(
                resolved_paths,
                resolved_destination,
                archive_name=archive_name,
            )

            return 1, {
                'archive_path': archive_path,
                'archive_name': scope.archive_service.normalize_zip_archive_name(
                    archive_name,
                    fallback=scope.archive_service.build_download_archive_name(resolved_paths),
                ),
                'source_count': len(resolved_paths),
                'size': os.path.getsize(archive_path),
            }
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to create ZIP archive: {e}'

    def peek_archive(self, scope, payload):
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid ZIP peek payload'

            archive_path = scope.path_resolver.require_existing_file(payload.get('path', ''))
            result = scope.archive_service.inspect_zip(archive_path)
            return 1, result
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to inspect ZIP archive: {e}'

    def read_archive_entry(self, scope, payload):
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid ZIP entry payload'

            archive_path = scope.path_resolver.require_existing_file(payload.get('path', ''))
            entry_name = str(payload.get('entry_name') or '').strip()
            if not entry_name:
                return 0, 'entry_name is required'

            result = scope.archive_service.read_zip_text_entry(archive_path, entry_name)
            return 1, result
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to read ZIP entry: {e}'

    def extract_archive(self, scope, payload):
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid ZIP extract payload'

            archive_path = scope.path_resolver.require_existing_file(payload.get('path', ''))
            destination_dir = str(payload.get('destination_dir') or '').strip()
            if not destination_dir:
                return 0, 'destination_dir is required'

            resolved_destination = scope.path_resolver.require_existing_directory(destination_dir)
            entry_name = str(payload.get('entry_name') or '')
            if payload.get('inspect') is True:
                result = scope.archive_service.inspect_extract_target(archive_path, resolved_destination, entry_name)
            elif 'conflict_policy' in payload:
                result = scope.archive_service.extract_zip_with_policy(
                    archive_path, resolved_destination, entry_name, str(payload['conflict_policy']))
            else:
                result = scope.archive_service.extract_zip_with_policy(
                    archive_path, resolved_destination, entry_name, 'stop')
            return 1, result
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to extract ZIP archive: {e}'

    def browse_directory(self, scope, payload):
        try:
            directory = scope.path_resolver.require_existing_directory(payload.get('path', ''))
            page = payload.get('page', 1)
            page_size = payload.get('page_size', 100)
            show_hidden = payload.get('show_hidden', False)
            search_keyword = payload.get('search_keyword') or payload.get('search') or ''
            recursive_search = payload.get('recursive_search', False)

            result_payload = scope.file_system_service.browse_directory(
                directory,
                page=page,
                page_size=page_size,
                show_hidden=show_hidden,
                search_keyword=search_keyword,
                recursive_search=recursive_search,
            )
            return 1, result_payload
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to browse directory: {e}'

    def delete_paths(self, scope, payload):
        """
        批量删除多个文件或目录
        参数格式: JSON object {"paths": ["path1", "path2", ...]}
        """
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid delete payload'

            paths = payload.get('paths')
            if not isinstance(paths, list) or not paths:
                return 0, 'paths is required and must be a non-empty list'

            return 1, scope.file_system_service.delete_paths(paths).to_dict()
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to delete paths: {e}'

    def create_directory(self, scope, payload):
        try:
            target_path = scope.path_resolver.resolve_target_path(
                payload.get('path', '')
            )
            if not target_path:
                return 0, 'Path is required'

            scope.file_system_service.create_directory(target_path)
            return 1, f'Directory created: {target_path}'
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to create directory: {e}'

    def rename_path(self, scope, payload):
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid rename payload'

            old_path = scope.path_resolver.require_existing_non_empty_path(payload.get('old_path', ''))
            new_name = (payload.get('new_name') or '').strip()
            new_path = (payload.get('new_path') or '').strip()

            renamed_path = scope.file_system_service.rename_target_path(
                old_path=old_path,
                new_name=new_name,
                new_path=new_path
            )
            return 1, f'Renamed to: {renamed_path}'
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to rename path: {e}'

    def inspect_upload(self, scope, payload):
        try:
            from client.runtime.filesystem.conflict_policy import path_kind, allowed_actions
            if not isinstance(payload, dict):
                return 0, 'Invalid inspect upload payload'
            directory = scope.path_resolver.require_existing_directory(payload.get('destination_dir', ''))
            filename = str(payload.get('filename') or '')
            if not filename or filename in ('.', '..') or os.path.basename(filename) != filename or '\\' in filename or '/' in filename:
                return 0, 'Invalid upload filename'
            target = os.path.join(directory, filename)
            kind = path_kind(target)
            conflicts = ([{'source': filename, 'target': target, 'source_kind': 'file',
                           'target_kind': kind, 'allowed_actions': allowed_actions('file', kind)}]
                         if kind else [])
            return 1, {'conflicts': conflicts}
        except Exception as exc:
            return 0, f'Failed to inspect upload: {exc}'

    def paste_paths(self, scope, payload):
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid paste payload'

            raw_paths = payload.get('paths') or []
            destination_dir = scope.path_resolver.require_existing_directory(payload.get('destination_dir', ''))
            operation = str(payload.get('operation', 'copy') or 'copy').strip().lower()

            if operation not in ('copy', 'move'):
                return 0, 'operation must be copy or move'

            if not isinstance(raw_paths, list) or not raw_paths:
                return 0, 'paths is required and must be a non-empty list'

            inspect = payload.get('inspect') is True
            policies = payload.get('conflict_policies')
            if policies is not None and (not isinstance(policies, list) or len(policies) != len(raw_paths)):
                return 0, 'Invalid conflict policies'
            result = scope.file_system_service.paste_paths(raw_paths, destination_dir, operation, policies=policies, inspect=inspect)
            return 1, result if inspect else result.to_dict()
        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to paste paths: {e}'

    def save_file(self, scope, payload):
        """
        保存内容到文件
        参数格式: JSON object
        {
            "path": "/path/to/file",
            "content": "file content",
            "encoding": "utf-8"  # 可选，默认 utf-8
        }
        """
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid save payload'

            file_path = payload.get('path', '').strip()
            content = payload.get('content', '')
            encoding = payload.get('encoding', 'utf-8')

            if not file_path:
                return 0, 'path is required'

            target_path, file_size, encoding = scope.file_system_service.save_file_content(
                file_path,
                content,
                encoding,
            )

            return 1, f'File saved successfully\nPath: {target_path}\nSize: {file_size} bytes\nEncoding: {encoding}'

        except CommandCancelledError:
            return 0, 'Command cancelled'
        except CommandTimeoutError:
            return 0, 'Command timed out and was terminated'
        except Exception as e:
            return 0, f'Failed to save file: {e}'
