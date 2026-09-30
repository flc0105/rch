class WebNotificationPreferencesApi:
    """SSE 通知偏好 Web 子外观。"""

    def __init__(self, preference_store, event_bus=None):
        self.preference_store = preference_store
        self.event_bus = event_bus

    def get_preferences(self):
        return self.preference_store.get_preferences()

    def is_delivery_enabled(self, notification_key: str) -> bool:
        return self.preference_store.is_delivery_enabled(notification_key)

    def save_preferences(self, payload: dict):
        preferences = self.preference_store.save_preferences(payload or {})
        if self.event_bus is not None:
            self.event_bus.publish('notification_preferences_updated', preferences)
        return preferences
