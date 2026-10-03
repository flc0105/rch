import os


class ArtifactReferenceViewProjector:
    """Resolve a persisted artifact reference into the current read-model view."""

    _COMMON_FIELDS = (
        'artifact_type',
        'category',
        'hostname',
        'machine_id',
        'client_id',
        'original_name',
        'stored_name',
        'size',
        'download_url',
        'raw_url',
        'preview_url',
    )

    def project(
        self,
        file_item: dict,
        artifact_service=None,
        *,
        path_key: str = 'saved_path',
        allow_local_path_fallback: bool = False,
        include_created_at: bool = False,
    ) -> dict:
        copied = dict(file_item or {})
        artifact_id = str(copied.get('artifact_id') or '').strip()

        if artifact_id and artifact_service is not None:
            try:
                artifact = artifact_service.get_artifact_by_id(artifact_id)
                for key in self._COMMON_FIELDS:
                    copied[key] = artifact.get(key, copied.get(key, ''))
                if include_created_at:
                    copied['created_at'] = artifact.get('created_at', copied.get('created_at', ''))
                copied[path_key] = artifact.get('saved_path', copied.get(path_key, ''))
                copied['is_available'] = artifact.get('is_available', True)
                copied['status_text'] = artifact.get('status_text', '')
                return copied
            except Exception:
                copied['is_available'] = False
                copied['status_text'] = copied.get('status_text') or 'Artifact removed'
                return copied

        if allow_local_path_fallback:
            local_path = copied.get(path_key, '')
            is_available = bool(local_path) and os.path.isfile(local_path)
            copied['is_available'] = is_available
            copied['status_text'] = '' if is_available else 'File removed'
            return copied

        copied['is_available'] = False
        copied['status_text'] = copied.get('status_text') or 'Artifact removed'
        return copied
