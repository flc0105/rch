from server.application.artifact.artifact_reference_view_projector import ArtifactReferenceViewProjector


class BackgroundJobViewService:
    """
    Background job presentation layer.

    Summary list queries stay lightweight. Artifact resolution and message/file
    expansion happen only when a single job detail is requested.
    """

    def __init__(self, store):
        self.store = store
        self.artifact_view_projector = ArtifactReferenceViewProjector()

    def _resolve_job_file_view(self, file_item: dict) -> dict:
        return self.artifact_view_projector.project(
            file_item,
            self.store.artifact_service,
            path_key='relative_path',
            allow_local_path_fallback=False,
        )

    def get_jobs_for_scope(self, machine_id: str = '', client_id: str = '') -> list[dict]:
        # Summary rows intentionally do not expand messages/files.
        return self.store.list_raw_jobs(machine_id=machine_id, client_id=client_id)

    def get_job_for_scope(self, job_id: str, machine_id: str = '', client_id: str = '') -> dict | None:
        item = self.store.get_raw_job(job_id, machine_id=machine_id, client_id=client_id)
        if item is None:
            return None

        files = [self._resolve_job_file_view(file_item) for file_item in item.get('files') or []]
        item['files'] = files
        return item
