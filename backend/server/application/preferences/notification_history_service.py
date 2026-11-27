class NotificationHistoryService:
    """通知历史查询、删除与事件发布。"""

    def __init__(self, history_store, event_bus=None):
        self.history_store = history_store
        self.event_bus = event_bus

    def get_history(self, *, limit: int = 20, offset: int = 0,
                    notification_type: str = ''):
        if notification_type and notification_type not in {'success', 'info', 'warning', 'error'}:
            raise ValueError('Invalid notification type')
        return self.history_store.get_history(
            limit=limit, offset=offset, notification_type=notification_type,
        )

    def list_cleanup_candidates(self):
        return self.history_store.list_cleanup_candidates()

    def get_notifications_after(self, notification_id: str):
        return self.history_store.get_notifications_after(notification_id)

    def delete_notification(self, notification_id: str):
        deleted = self.history_store.delete_notification(notification_id)
        if deleted and self.event_bus is not None:
            self.event_bus.publish('notification_center_updated', {
                'action': 'deleted',
                'id': str(notification_id or '').strip(),
            })
        return {'deleted': deleted}

    def clear_history(self, notification_type: str = ''):
        if notification_type:
            if notification_type not in {'success', 'info', 'warning', 'error'}:
                raise ValueError('Invalid notification type')
            removed_ids = self.history_store.clear_type(notification_type)
            if removed_ids and self.event_bus is not None:
                self.event_bus.publish('notification_center_updated', {
                    'action': 'pruned',
                    'ids': removed_ids,
                })
            return {'removed_count': len(removed_ids)}

        removed_count = self.history_store.clear_history()
        if self.event_bus is not None:
            self.event_bus.publish('notification_center_updated', {
                'action': 'cleared',
                'removed_count': removed_count,
            })
        return {'removed_count': removed_count}

    def cleanup_notifications(self, notification_ids, *, expected=None):
        result = self.history_store.delete_notifications(notification_ids, expected=expected)
        removed = result.get('removed') if isinstance(result, dict) else []
        removed = removed if isinstance(removed, list) else []
        removed_ids = [
            str(item.get('id') or '').strip()
            for item in removed
            if str(item.get('id') or '').strip()
        ]
        if removed_ids and self.event_bus is not None:
            self.event_bus.publish('notification_center_updated', {
                'action': 'pruned',
                'ids': removed_ids,
            })
        return result
