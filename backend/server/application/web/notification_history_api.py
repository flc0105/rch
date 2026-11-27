class WebNotificationHistoryApi:
    """Serialize public notification history operations."""

    def __init__(self, notification_service):
        self.notification_service = notification_service

    def get_history(self, *, limit=20, offset=0, notification_type=''):
        return self.notification_service.get_history(limit=limit, offset=offset, notification_type=notification_type)

    def get_notifications_after(self, notification_id):
        return self.notification_service.get_notifications_after(notification_id)

    def delete_notification(self, notification_id):
        return self.notification_service.delete_notification(notification_id)

    def clear_history(self, notification_type=''):
        return self.notification_service.clear_history(notification_type)
