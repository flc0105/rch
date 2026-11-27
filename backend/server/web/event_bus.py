import asyncio
from collections import OrderedDict, deque
import queue
import threading
import time
import uuid
from typing import Dict, List

from core.utils.logger import logger


class WebEventBus:
    """
    线程安全事件总线，供浏览器 WebSocket 和内部服务使用。

    支持：
    - 全局广播事件
    - 按 tab_id 定向推送事件
    - 在 WebSocket 投递前由 Server 持久化可通知事件

    设计原则：
    - 连接状态 / artifact / background job 等全局事件继续广播
    - 前台命令输出类事件可按 tab_id 定向，避免多个浏览器页签互相污染
    - Notification Center 的持久化不依赖浏览器是否成功消费实时事件
    """

    def __init__(self):
        self._subscribers: List[dict] = []
        self._lock = threading.RLock()
        self._notification_recorder = None
        # Bounded per-tab replay for short WS outages. Only terminal task events
        # belong here; notification/history/PTY streams have separate semantics.
        self._command_sequence = 0
        self._replay_epoch = uuid.uuid4().hex
        self._command_events = OrderedDict()
        self._command_replay_types = frozenset({
            'command_result', 'command_result_batch', 'command_complete'})

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

    def subscribe_async(self, tab_id='', event_types=None, max_pending=512, *,
                        replay_after=None, replay_epoch='', with_cursor=False):
        """Register an asyncio consumer; optionally resume tab command events."""
        loop = asyncio.get_running_loop()
        q = asyncio.Queue(maxsize=max_pending)
        filtered = {str(value).strip() for value in event_types} if event_types else None
        tab = str(tab_id or '').strip()
        with self._lock:
            if replay_after is not None and tab and replay_epoch == self._replay_epoch:
                for seq, timestamp, event, _size in self._command_events.get(tab, ()):
                    if seq > replay_after and time.monotonic() - timestamp <= 90:
                        if q.full():
                            # Do not deliver a misleading partial replay.
                            while not q.empty():
                                q.get_nowait()
                            q.put_nowait(None)
                            break
                        q.put_nowait(event)
            if with_cursor:
                if not q.full():
                    q.put_nowait({'event': 'stream_cursor', 'data': {},
                                  'cursor': self._command_sequence, 'epoch': self._replay_epoch})
            self._subscribers.append({
                'queue': q, 'loop': loop, 'tab_id': tab,
                'event_types': filtered, 'overflowed': False,
            })
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
            # Command output has no broadcast semantics, even if an API caller
            # omitted its tab header. Durable Activity/notifications still work.
            return event_type not in self._command_replay_types

        subscriber_tab_id = str(subscriber.get('tab_id') or '').strip()
        return subscriber_tab_id == normalized_target_tab_id

    def publish(self, event_type: str, data: Dict, target_tab_id: str = ''):
        event_id = uuid.uuid4().hex
        event_item = {'id': event_id, 'event': event_type, 'data': data}

        notification = self._record_notification(
            event_type=event_type, data=data, event_id=event_id,
            target_tab_id=target_tab_id,
        )

        # Registration, retention and delivery must be atomic: otherwise a
        # reconnect between storing and broadcasting could receive a duplicate.
        with self._lock:
            if target_tab_id and event_type in self._command_replay_types:
                self._command_sequence += 1
                event_item['cursor'] = self._command_sequence
                self._remember_command_event(str(target_tab_id).strip(), event_item)
            self._deliver(event_item, target_tab_id=target_tab_id)

        if notification:
            self._deliver({
                'id': uuid.uuid4().hex,
                'event': 'notification_center_updated',
                'data': {'action': 'added', 'notification': notification},
            })
        return event_id

    def _remember_command_event(self, tab, event):
        if not tab:
            return
        from json import dumps
        size = len(dumps(event, ensure_ascii=False).encode('utf-8'))
        # Larger results remain live-only; retaining unbounded command output
        # would make a disconnected tab consume unbounded Server memory.
        if size > 1024 * 1024:
            return
        now = time.monotonic()
        history = self._command_events.setdefault(tab, deque())
        self._command_events.move_to_end(tab)
        history.append((event['cursor'], now, event, size))
        used = sum(item[3] for item in history)
        while history and (len(history) > 128 or used > 1024 * 1024 or
                           now - history[0][1] > 90):
            used -= history.popleft()[3]
        while len(self._command_events) > 32:
            self._command_events.popitem(last=False)

    def _record_notification(self, *, event_type: str, data: Dict, event_id: str, target_tab_id: str):
        recorder = self._notification_recorder
        if recorder is None:
            return None
        if event_type in {'notification_center_updated', 'notification_preferences_updated',
                          'interaction_requested', 'interaction_resolved',
                          'foreground_task_changed'}:
            return None
        try:
            return recorder(event_type, data, event_id, target_tab_id)
        except Exception:
            logger.error('Failed to persist notification for web event: %s', event_type, exc_info=True)
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
                loop = subscriber.get('loop')
                if loop is not None:
                    def deliver(current_queue=q, current_subscriber=subscriber, event=event_item):
                        if current_subscriber['overflowed']:
                            return
                        if current_queue.full():
                            # Disconnect a slow consumer, so it reloads durable state.
                            current_subscriber['overflowed'] = True
                            while not current_queue.empty():
                                current_queue.get_nowait()
                            current_queue.put_nowait(None)
                        else:
                            current_queue.put_nowait(event)
                    loop.call_soon_threadsafe(deliver)
                else:
                    q.put_nowait(event_item)
            except RuntimeError:
                self.unsubscribe(q)
            except Exception:
                logger.error('Failed to deliver web event', exc_info=True)
