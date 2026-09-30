import queue
import threading
import uuid
from typing import Dict, List

from core.utils.logger import logger


class WebEventBus:
    """
    简单线程安全事件总线，供 SSE 使用。

    支持：
    - 全局广播事件
    - 按 tab_id 定向推送事件
    - 在 SSE 投递前由 Server 持久化可通知事件

    设计原则：
    - 连接状态 / artifact / background job 等全局事件继续广播
    - 前台命令输出类事件可按 tab_id 定向，避免多个浏览器页签互相污染
    - Notification Center 的持久化不依赖浏览器是否成功消费 SSE
    """

    def __init__(self):
        self._subscribers: List[dict] = []
        self._lock = threading.RLock()
        self._notification_recorder = None

    def set_notification_recorder(self, recorder):
        self._notification_recorder = recorder

    def subscribe(self, tab_id: str = '', event_types=None) -> queue.Queue:
        q = queue.Queue()
        normalized_event_types = None
        if event_types:
            normalized_event_types = {
                str(value or '').strip()
                for value in event_types
                if str(value or '').strip()
            }
            if not normalized_event_types:
                normalized_event_types = None

        subscriber = {
            'queue': q,
            'tab_id': str(tab_id or '').strip(),
            'event_types': normalized_event_types,
        }
        with self._lock:
            self._subscribers.append(subscriber)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._subscribers = [
                item for item in self._subscribers
                if item.get('queue') is not q
            ]

    def _should_deliver(self, subscriber: dict, target_tab_id: str, event_type: str) -> bool:
        normalized_event_types = subscriber.get('event_types')
        if normalized_event_types is not None and str(event_type or '').strip() not in normalized_event_types:
            return False

        normalized_target_tab_id = str(target_tab_id or '').strip()
        if not normalized_target_tab_id:
            return True

        subscriber_tab_id = str(subscriber.get('tab_id') or '').strip()
        return subscriber_tab_id == normalized_target_tab_id

    def publish(self, event_type: str, data: Dict, target_tab_id: str = ''):
        event_id = uuid.uuid4().hex
        event_item = {
            'id': event_id,
            'event': event_type,
            'data': data,
        }

        notification = self._record_notification(
            event_type=event_type,
            data=data,
            event_id=event_id,
            target_tab_id=target_tab_id,
        )

        self._deliver(event_item, target_tab_id=target_tab_id)

        if notification:
            self._deliver({
                'id': uuid.uuid4().hex,
                'event': 'notification_center_updated',
                'data': {
                    'action': 'added',
                    'notification': notification,
                },
            })

        return event_id

    def _record_notification(self, *, event_type: str, data: Dict, event_id: str, target_tab_id: str):
        recorder = self._notification_recorder
        if recorder is None:
            return None
        if event_type in {'notification_center_updated', 'notification_preferences_updated'}:
            return None
        try:
            return recorder(event_type, data, event_id, target_tab_id)
        except Exception:
            logger.error('Failed to persist notification for SSE event: %s', event_type, exc_info=True)
            return None

    def _deliver(self, event_item: dict, target_tab_id: str = ''):
        with self._lock:
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            if not self._should_deliver(subscriber, target_tab_id, event_item.get('event')):
                continue

            q = subscriber.get('queue')
            if q is None:
                continue

            try:
                q.put_nowait(event_item)
            except Exception:
                pass
