class WebServerCleanupApi:
    """Web-facing cleanup facade."""

    def __init__(self, cleanup_service):
        self.cleanup_service = cleanup_service

    def schedule_startup_cleanup(self) -> bool:
        return self.cleanup_service.schedule_startup_cleanup()

    def get_log_path(self, run_id: str) -> str:
        return self.cleanup_service.get_log_path(run_id)

    def summary(self):
        return self.cleanup_service.summary()

    def preview(self):
        return self.cleanup_service.preview()

    def execute(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('Invalid cleanup request')
        return self.cleanup_service.execute(payload.get('plan_id'), payload.get('selected_ids'))

    def save_settings(self, payload):
        return self.cleanup_service.save_settings(payload)

    def database_info(self):
        return self.cleanup_service.database_info()

    def optimize_database(self):
        return self.cleanup_service.optimize_database()

    def get_run(self, run_id):
        return self.cleanup_service.get_run(run_id)

    def cancel_run(self, run_id):
        return self.cleanup_service.cancel_run(run_id)

    def is_busy(self):
        return self.cleanup_service.is_busy()

    def reserve_stop(self):
        return self.cleanup_service.reserve_stop()
