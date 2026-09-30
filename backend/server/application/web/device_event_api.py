class WebDeviceEventApi:
    def __init__(self, device_event_service):
        self.device_event_service = device_event_service

    def ingest(self, payload: dict) -> dict:
        return self.device_event_service.ingest(payload)
