import json
import mimetypes
import os


class WebClipboardApi:
    def __init__(self, clipboard_session_service, artifact_service):
        self.clipboard_session_service = clipboard_session_service
        self.artifact_service = artifact_service

    def get_capabilities(self, client_id: str) -> dict:
        payload = self.clipboard_session_service.get_capabilities(client_id)
        return payload.get('capabilities') if isinstance(payload.get('capabilities'), dict) else {}

    def get_clipboard(self, client_id: str) -> dict:
        return self.clipboard_session_service.get_clipboard(client_id)

    def set_text(self, client_id: str, text: str) -> dict:
        content = str(text or '')
        return self.clipboard_session_service.set_clipboard(
            client_id,
            {'kind': 'text', 'text': content},
            action='set_text',
            arguments={
                'text': content[:2048], 'length': len(content),
                'truncated': len(content) > 2048,
            },
        )

    def set_image(self, client_id: str, upload) -> dict:
        temp_paths = []
        try:
            item, temp_path = self._stage_upload(upload)
            temp_paths.append(temp_path)
            return self.clipboard_session_service.set_clipboard(
                client_id,
                {'kind': 'image', 'items': [item]},
                action='set_image',
                arguments={
                    'filename': str(item.get('name') or '')[:160],
                    'mime_type': mimetypes.guess_type(str(item.get('name') or ''))[0] or 'application/octet-stream',
                    'size_bytes': os.path.getsize(temp_path),
                },
            )
        finally:
            self._cleanup_temp_paths(temp_paths)

    def set_files(self, client_id: str, uploads: list, manifest_text: str) -> dict:
        try:
            manifest = json.loads(str(manifest_text or ''))
        except Exception as e:
            raise ValueError('clipboard file manifest is required') from e

        if not isinstance(manifest, dict):
            raise ValueError('clipboard file manifest is invalid')

        entries = manifest.get('entries') if isinstance(manifest.get('entries'), list) else []
        roots = manifest.get('roots') if isinstance(manifest.get('roots'), list) else []
        if not entries or not roots:
            raise ValueError('clipboard file manifest is empty')

        temp_paths = []
        items = []
        try:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                entry_type = str(entry.get('type') or '').strip().lower()
                relative_path = str(entry.get('path') or '').strip()
                if not relative_path:
                    continue

                if entry_type == 'directory':
                    items.append({
                        'type': 'directory',
                        'path': relative_path,
                    })
                    continue

                if entry_type != 'file':
                    continue

                try:
                    upload_index = int(entry.get('upload_index'))
                except Exception as e:
                    raise ValueError('clipboard file upload index is invalid') from e

                if upload_index < 0 or upload_index >= len(uploads):
                    raise ValueError('clipboard file upload is missing')

                upload = uploads[upload_index]
                if not upload or not getattr(upload, 'filename', ''):
                    raise ValueError('clipboard file upload is missing')

                item, temp_path = self._stage_upload(upload)
                item.update({
                    'type': 'file',
                    'path': relative_path,
                })
                items.append(item)
                temp_paths.append(temp_path)

            if not items:
                raise ValueError('clipboard file manifest is empty')

            normalized_roots = [
                str(root or '').strip()
                for root in roots
                if str(root or '').strip()
            ]
            if not normalized_roots:
                raise ValueError('clipboard file roots are empty')

            return self._set_files_payload(client_id, items, normalized_roots, action='set_files')
        finally:
            self._cleanup_temp_paths(temp_paths)

    def set_artifact_file(self, client_id: str, artifact_id: str) -> dict:
        normalized_artifact_id = str(artifact_id or '').strip()
        if not normalized_artifact_id:
            raise ValueError('artifact_id is required')

        capabilities = self.get_capabilities(client_id)
        if not capabilities.get('files'):
            raise RuntimeError('Target clipboard does not support files')

        artifact = self.artifact_service.get_artifact_by_id(normalized_artifact_id)
        if str(artifact.get('artifact_type') or '').strip() != 'shared':
            raise ValueError('Only shared files can be sent to clipboard')

        source_path = self.artifact_service.get_artifact_file_path(normalized_artifact_id)
        display_name = str(
            artifact.get('original_name')
            or artifact.get('stored_name')
            or ''
        ).strip()
        display_name = os.path.basename(display_name) or os.path.basename(source_path)

        temp_paths = []
        try:
            temp_path, _safe_name = self.artifact_service.stage_local_file(source_path, display_name)
            temp_paths.append(temp_path)
            relative_url = self.artifact_service.build_upload_temp_download_relative_url(temp_path)
            return self._set_files_payload(
                client_id,
                [{
                    'type': 'file',
                    'path': display_name,
                    'name': display_name,
                    'url': relative_url,
                }],
                [display_name],
                action='set_artifact_file', artifact_id=normalized_artifact_id,
            )
        finally:
            self._cleanup_temp_paths(temp_paths)

    def _set_files_payload(self, client_id: str, items: list, roots: list, *, action: str, artifact_id='') -> dict:
        arguments = {
            'count': len(roots),
            'names': [str(name).replace('\\', '/').split('/')[-1][:160] for name in roots[:20]],
            'names_truncated': len(roots) > 20,
        }
        if artifact_id:
            arguments['artifact_id'] = artifact_id
        return self.clipboard_session_service.set_clipboard(
            client_id,
            {
                'kind': 'files',
                'items': items,
                'roots': roots,
            },
            action=action, arguments=arguments,
        )

    def _stage_upload(self, upload) -> tuple[dict, str]:
        temp_path, safe_name = self.artifact_service.create_upload_temp_file(upload)
        relative_url = self.artifact_service.build_upload_temp_download_relative_url(temp_path)
        return {'name': safe_name, 'url': relative_url}, temp_path

    def _cleanup_temp_paths(self, paths: list[str]):
        for path in paths:
            try:
                self.artifact_service.cleanup_upload_temp_file(path)
            except Exception:
                pass
