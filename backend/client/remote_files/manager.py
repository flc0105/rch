import os
from contextlib import nullcontext
from client.runtime.filesystem.mutation_guard import filesystem_mutation
from client.runtime.filesystem.path_resolver import PathResolver

from core.protocol.control import RemoteFilesAction
from core.protocol.result_envelope import ResultEnvelope
from client.runtime.execution.context import CommandCancelledError, CommandTimeoutError


class RemoteFilesManager:
    """Structured remote file operations; one scope per request."""

    # Path fields are resolved against one cwd snapshot at request admission.
    QUERY_PATH_FIELDS = {
        RemoteFilesAction.BROWSE_DIRECTORY: 'path',
        RemoteFilesAction.PEEK_ARCHIVE: 'path',
        RemoteFilesAction.READ_ARCHIVE_ENTRY: 'path',
        RemoteFilesAction.INSPECT_UPLOAD: 'destination_dir',
    }
    WRITE_PATH_FIELDS = {
        RemoteFilesAction.CREATE_DIRECTORY: ('path',),
        RemoteFilesAction.RENAME_PATH: ('old_path', 'new_path'),
        RemoteFilesAction.DELETE_PATHS: ('paths',),
        RemoteFilesAction.PASTE_PATHS: ('paths', 'destination_dir'),
        RemoteFilesAction.CREATE_ARCHIVE: ('paths', 'destination_dir'),
        RemoteFilesAction.EXTRACT_ARCHIVE: ('path', 'destination_dir'),
        RemoteFilesAction.SAVE_FILE: ('path',),
    }

    def prepare_paths(self, action, payload):
        resolver = PathResolver()
        cwd = resolver.get_current_directory()
        def resolve(value):
            return resolver.resolve_target_path(value, base_dir=cwd)
        result = dict(payload)
        if action in self.QUERY_PATH_FIELDS:
            field = self.QUERY_PATH_FIELDS[action]
            result[field] = resolve(payload.get(field, ''))
            return result
        for field in self.WRITE_PATH_FIELDS[action]:
            value = payload.get(field)
            if field == 'paths' and isinstance(value, list):
                paths = []
                for item in value:
                    if isinstance(item, dict) and action == RemoteFilesAction.CREATE_ARCHIVE:
                        raw = item.get('path')
                        paths.append({**item, 'path': resolve(raw)} if isinstance(raw, str) and raw.strip() else item)
                    else:
                        paths.append(resolve(item) if isinstance(item, str) and item.strip() else item)
                result[field] = paths
            elif isinstance(value, str) and value.strip():
                result[field] = resolve(value)
            elif field == 'path' and action in (RemoteFilesAction.CREATE_DIRECTORY, RemoteFilesAction.EXTRACT_ARCHIVE):
                # These existing handlers resolve empty paths to cwd before validation.
                result[field] = resolve(value or '')
        return result

    def execute(self, scope, action, payload):
        handler = self.actions.get(action)
        if handler is None:
            return 0, f'Unsupported remote_files Control action: {action}'
        guard = filesystem_mutation(scope._checkpoint) if action in self.WRITE_PATH_FIELDS else nullcontext()
        with guard:
            result = handler(scope, payload)
        if action in self.QUERY_PATH_FIELDS:
            scope._checkpoint()
        return result

    @staticmethod
    def _batch_result(result):
        summary = result.to_dict()
        state = ('success' if result.failed == 0 else
                 'partial' if result.succeeded > 0 else 'error')
        # Only the message and two figures used by the paste UI are returned.
        return int(result.failed == 0), ResultEnvelope(
            status=state, message=summary['message'],
            data=({'succeeded': result.succeeded, 'failed': result.failed}
                  if result.action != 'delete' else None),
        ).as_payload()

    @property
    def actions(self):
        return {
            RemoteFilesAction.BROWSE_DIRECTORY: self.browse_directory,
            RemoteFilesAction.CREATE_DIRECTORY: self.create_directory,
            RemoteFilesAction.RENAME_PATH: self.rename_path,
            RemoteFilesAction.DELETE_PATHS: self.delete_paths,
            RemoteFilesAction.PASTE_PATHS: self.paste_paths,
            RemoteFilesAction.CREATE_ARCHIVE: self.create_archive,
            RemoteFilesAction.PEEK_ARCHIVE: self.peek_archive,
            RemoteFilesAction.READ_ARCHIVE_ENTRY: self.read_archive_entry,
            RemoteFilesAction.EXTRACT_ARCHIVE: self.extract_archive,
            RemoteFilesAction.INSPECT_UPLOAD: self.inspect_upload,
            RemoteFilesAction.SAVE_FILE: self.save_file,
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

            return 1, ResultEnvelope(data={
                'archive_name': scope.archive_service.normalize_zip_archive_name(
                    archive_name,
                    fallback=scope.archive_service.build_download_archive_name(resolved_paths),
                ),
            }).as_payload()
        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as e:
            return 0, f'Failed to create ZIP archive: {e}'

    def peek_archive(self, scope, payload):
        try:
            if not isinstance(payload, dict):
                return 0, 'Invalid ZIP peek payload'

            archive_path = scope.path_resolver.require_existing_file(payload.get('path', ''))
            result = scope.archive_service.inspect_zip(archive_path)
            fields = ('path', 'name', 'archive_size', 'file_count', 'dir_count',
                      'entry_count', 'uncompressed_size', 'tree')
            return 1, {name: result[name] for name in fields if name in result}
        except (CommandCancelledError, CommandTimeoutError):
            raise
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
            fields = ('type', 'content', 'message')
            return 1, {name: result[name] for name in fields if name in result}
        except (CommandCancelledError, CommandTimeoutError):
            raise
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
            if payload.get('inspect') is True:
                return 1, result
            return 1, ResultEnvelope(data={'extracted_to': result.get('extracted_to', resolved_destination)}).as_payload()
        except (CommandCancelledError, CommandTimeoutError):
            raise
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
        except (CommandCancelledError, CommandTimeoutError):
            raise
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

            result = scope.file_system_service.delete_paths(paths)
            return self._batch_result(result)
        except (CommandCancelledError, CommandTimeoutError):
            raise
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
            return 1, ResultEnvelope(message=f'Directory created: {target_path}').as_payload()
        except (CommandCancelledError, CommandTimeoutError):
            raise
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
            return 1, ResultEnvelope(message=f'Renamed to: {renamed_path}').as_payload()
        except (CommandCancelledError, CommandTimeoutError):
            raise
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
            return (1, result) if inspect else self._batch_result(result)
        except (CommandCancelledError, CommandTimeoutError):
            raise
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

            return 1, ResultEnvelope(message=(f'File saved successfully\nPath: {target_path}\n'
                                              f'Size: {file_size} bytes\nEncoding: {encoding}')).as_payload()

        except (CommandCancelledError, CommandTimeoutError):
            raise
        except Exception as e:
            return 0, f'Failed to save file: {e}'
