
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

    def stop_background_job(self, client_id: str, job_key: str, *, origin='web_api'):
        return self.background_job_service.stop_job(client_id, job_key, origin=origin)

    def ingest_background_job_report(self, payload: dict):
        return self.background_job_service.ingest_report(payload)

    def list_background_job_catalog(self, client_id: str):
        del client_id
        return self.job_catalog_service.list_background_job_catalog()

    def prepare_background_job_start(self, client_id: str, job_name: str, execution_mode: str | None = None):
        return self.background_job_service.prepare_job_start(client_id, job_name, execution_mode)

    def start_background_job(self, client_id: str, job_name: str, params=None, execution_mode: str | None = None, *, origin='web_api'):
        normalized_job_name = (job_name or '').strip()
        normalized_mode = self.prepare_background_job_start(client_id, normalized_job_name, execution_mode)
        result = self.background_job_service.start_job(
            client_id,
            normalized_job_name,
            params=params,
            execution_mode=normalized_mode,
            origin=origin,
        )
        if isinstance(result, dict):
            result['job_name'] = normalized_job_name
            result['params'] = dict(params or {}) if isinstance(params, dict) else {}
            result['execution_mode'] = str(result.get('execution_mode') or normalized_mode or 'inproc')
        return result
