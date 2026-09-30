import os

from core.utils.job_metadata import normalize_job_execution_allowed, normalize_job_execution_mode


class WebJobApi:
    """
    Web 后台任务子外观。

    职责：
    - 管理 job catalog
    - 管理 background jobs
    - 提供 background job catalog

    说明：
    - 路由层不再直接协调 job_catalog_service / background_job_service
    - 相关应用语义统一收口到这里
    """

    def __init__(self, background_job_service, job_catalog_service):
        self.background_job_service = background_job_service
        self.job_catalog_service = job_catalog_service

    # ------------------ job catalog api ------------------ #
    def list_jobs(self) -> list[dict]:
        return self.job_catalog_service.list_jobs()

    def get_job_content(self, job_name: str) -> str:
        return self.job_catalog_service.get_job_content(job_name)

    def save_job_content(self, job_name: str, content):
        return self.job_catalog_service.save_job(job_name, content)

    def upload_job(self, file_storage):
        return self.job_catalog_service.upload_job(file_storage)

    def delete_job(self, job_name: str):
        return self.job_catalog_service.delete_job(job_name)

    # ------------------ background job api ------------------ #
    def list_background_jobs(self, client_id: str):
        return self.background_job_service.list_jobs(client_id)

    def get_background_job(self, client_id: str, job_id: str):
        return self.background_job_service.get_job(client_id, job_id)

    def delete_background_job_record(self, client_id: str, job_id: str):
        return self.background_job_service.delete_job_record(client_id, job_id)

    def list_available_background_jobs(self, client_id: str):
        return self.background_job_service.list_available_jobs(client_id)

    def stop_background_job(self, client_id: str, job_key: str):
        return self.background_job_service.stop_job(client_id, job_key)

    def ingest_background_job_report(self, payload: dict):
        return self.background_job_service.ingest_report(payload)

    def list_background_job_catalog(self, client_id: str):
        del client_id
        normalized = []
        seen = set()

        for item in self.list_jobs() or []:
            if not isinstance(item, dict):
                continue

            job_name = str(item.get('job_name') or item.get('name') or item.get('job_key') or '').strip()
            if not job_name:
                continue

            dedupe_key = job_name
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            normalized.append({
                **item,
                'job_name': job_name,
                'job_key': str(item.get('job_key') or job_name).strip() or job_name,
                'display_name': str(item.get('display_name') or item.get('name') or job_name).strip() or job_name,
                'description': str(item.get('description') or '').strip(),
                'metadata': item.get('metadata') or {},
                'source': 'job',
            })

        normalized.sort(key=lambda item: item.get('job_name', '').lower())
        return normalized

    def _normalize_job_key(self, value: str) -> str:
        text = str(value or '').strip().replace('\\', '/')
        if text.endswith('.py'):
            text = text[:-3]
        return os.path.basename(text)

    def _get_job_metadata(self, job_name: str) -> dict:
        target = str(job_name or '').strip().replace('\\', '/').removesuffix('.py')
        for item in self.list_jobs() or []:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get('job_name') or item.get('name') or '').strip().replace('\\', '/').removesuffix('.py')
            if candidate == target:
                metadata = item.get('metadata') or {}
                return metadata if isinstance(metadata, dict) else {}
        return {}

    def start_background_job(self, client_id: str, job_name: str, params=None, execution_mode: str = 'inproc'):
        normalized_job_name = (job_name or '').strip()
        if not normalized_job_name:
            raise ValueError('job_name is required')

        if self.background_job_service.has_active_job(client_id, normalized_job_name):
            job_key = self._normalize_job_key(normalized_job_name)
            raise ValueError(f'Job is already running: {job_key}')

        metadata = self._get_job_metadata(normalized_job_name)
        metadata_default = str(metadata.get('execution_mode') or 'inproc').strip() or 'inproc'
        normalized_mode = normalize_job_execution_mode(execution_mode, default=metadata_default)
        allowed_modes = normalize_job_execution_allowed(metadata.get('allowed'))
        if normalized_mode not in allowed_modes:
            raise ValueError(
                f'Execution mode "{normalized_mode}" is not supported by background job '
                f'"{normalized_job_name}"; allowed: {allowed_modes}'
            )

        result = self.background_job_service.start_job(
            client_id,
            normalized_job_name,
            params=params,
            execution_mode=normalized_mode,
        )
        if isinstance(result, dict):
            result['job_name'] = normalized_job_name
            result['params'] = dict(params or {}) if isinstance(params, dict) else {}
            result['execution_mode'] = str(result.get('execution_mode') or normalized_mode or 'inproc')
        return result