class BackgroundJobViewService:
    """
    Background job presentation layer.

    Summary list queries stay lightweight. Artifact resolution and message/file
    expansion happen only when a single job detail is requested.
    """

    def __init__(self, store):
        self.store = store

    def _resolve_job_file_view(self, file_item: dict) -> dict:
        copied = dict(file_item)
        artifact_id = (copied.get('artifact_id') or '').strip()

        if artifact_id and self.store.artifact_service is not None:
            try:
                artifact = self.store.artifact_service.get_artifact_by_id(artifact_id)
                copied.update({
                    'artifact_type': artifact.get('artifact_type', copied.get('artifact_type', '')),
                    'category': artifact.get('category', copied.get('category', '')),
                    'hostname': artifact.get('hostname', copied.get('hostname', '')),
                    'machine_id': artifact.get('machine_id', copied.get('machine_id', '')),
                    'client_id': artifact.get('client_id', copied.get('client_id', '')),
                    'original_name': artifact.get('original_name', copied.get('original_name', '')),
                    'stored_name': artifact.get('stored_name', copied.get('stored_name', '')),
                    'relative_path': artifact.get('saved_path', copied.get('relative_path', '')),
                    'size': artifact.get('size', copied.get('size', 0)),
                    'download_url': artifact.get('download_url', copied.get('download_url', '')),
                    'raw_url': artifact.get('raw_url', copied.get('raw_url', '')),
                    'preview_url': artifact.get('preview_url', copied.get('preview_url', '')),
                    'is_available': artifact.get('is_available', True),
                    'status_text': artifact.get('status_text', ''),
                })
                return copied
            except Exception:
                copied['is_available'] = False
                copied['status_text'] = copied.get('status_text') or 'Artifact removed'
                return copied

        copied['is_available'] = False
        copied['status_text'] = copied.get('status_text') or 'Artifact removed'
        return copied

    def get_jobs_for_scope(self, machine_id: str = '', client_id: str = '') -> list[dict]:
        # Summary rows intentionally do not expand messages/files.
        return self.store.list_raw_jobs(machine_id=machine_id, client_id=client_id)

    def get_job_for_scope(self, job_id: str, machine_id: str = '', client_id: str = '') -> dict | None:
        item = self.store.get_raw_job(job_id, machine_id=machine_id, client_id=client_id)
        if item is None:
            return None

        files = [self._resolve_job_file_view(file_item) for file_item in item.get('files') or []]
        item['files'] = files
        item['file_count'] = len(files)
        return item
