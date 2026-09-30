import logging
import math
import threading
import time
from typing import Callable, Optional

import requests

from .sse import NotificationSseClient, SseAuthenticationError


logger = logging.getLogger('rch_notifier')


StatusCallback = Callable[[bool, Optional[int]], None]


class NotificationStreamRuntime:
    """Own the notifier SSE lifecycle separately from any desktop UI.

    The runtime keeps exactly one streaming HTTP connection open. A reconnect
    request interrupts the current response and immediately establishes a new
    stream; normal connection failures use the configured exponential backoff.
    """

    def __init__(self, *, config, state, backend, status_callback: Optional[StatusCallback] = None):
        self.config = config
        self.state = state
        self.backend = backend
        self.status_callback = status_callback
        self.stop_event = threading.Event()
        self.reconnect_event = threading.Event()
        self.client = NotificationSseClient(url=config.stream_url, token=config.token)
        self.exit_code = 0

    def set_status_callback(self, callback: Optional[StatusCallback]):
        self.status_callback = callback

    def _publish_status(self, connected: bool, retry_seconds: Optional[int] = None):
        callback = self.status_callback
        if callback is None:
            return
        try:
            callback(bool(connected), retry_seconds)
        except Exception:
            logger.debug('Notifier status callback failed', exc_info=True)

    def _mark_connected(self):
        self._publish_status(True, None)

    def reconnect(self):
        if self.stop_event.is_set():
            return
        self.reconnect_event.set()
        # Closing the active streaming response wakes requests.iter_lines()
        # instead of waiting for the normal server heartbeat/read timeout.
        self.client.close_active_response()

    def stop(self):
        self.stop_event.set()
        self.reconnect_event.set()
        self.client.close_active_response()

    def _consume_reconnect_request(self) -> bool:
        requested = self.reconnect_event.is_set()
        if requested:
            self.reconnect_event.clear()
        return requested

    def _wait_for_retry(self, delay: float) -> bool:
        """Wait for the reconnect delay while publishing an integer countdown.

        Returns True when the caller should continue immediately because Stop or
        manual Reconnect was requested; False when the backoff elapsed normally.
        """

        deadline = time.monotonic() + max(0.0, float(delay))
        last_published = None
        while not self.stop_event.is_set():
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                return False

            seconds = max(1, int(math.ceil(remaining)))
            if seconds != last_published:
                self._publish_status(False, seconds)
                last_published = seconds

            wait_for = min(1.0, remaining)
            if self.reconnect_event.wait(wait_for):
                return True

        return True

    def run(self) -> int:
        delay = self.config.reconnect_initial_seconds
        self.exit_code = 0
        self._publish_status(False, None)

        while not self.stop_event.is_set():
            cursor = self.state.last_event_id
            logger.info('Connecting to %s%s', self.config.stream_url, f' after {cursor}' if cursor else '')

            try:
                for event in self.client.events(cursor, on_open=self._mark_connected):
                    if self.stop_event.is_set():
                        self.exit_code = 0
                        return self.exit_code
                    if event.event == 'ping':
                        continue
                    if event.event == 'reset':
                        logger.warning('Server no longer has the local SSE cursor; continuing from live events')
                        self.state.clear()
                        continue
                    if event.event != 'notification':
                        continue

                    notification = event.json()
                    notification_id = str(notification.get('id') or event.event_id or '').strip()
                    if not notification_id:
                        logger.warning('Ignoring notification without an id')
                        continue

                    self.backend.notify(notification)
                    self.state.update(notification_id)
                    logger.info('Notification delivered: %s', notification.get('title') or notification_id)
                    delay = self.config.reconnect_initial_seconds

                if self.stop_event.is_set():
                    self.exit_code = 0
                    return self.exit_code
                raise RuntimeError('SSE stream ended')
            except SseAuthenticationError:
                self._publish_status(False, None)
                logger.error('Authentication failed. Check the notifier token in the config.')
                self.exit_code = 2
                return self.exit_code
            except requests.RequestException as exc:
                self._publish_status(False, None)
                if not self.reconnect_event.is_set():
                    logger.warning('SSE connection error: %s', exc)
            except Exception as exc:
                self._publish_status(False, None)
                if not self.reconnect_event.is_set():
                    logger.warning(
                        'Notifier stream/delivery error: %s',
                        exc,
                        exc_info=logger.isEnabledFor(logging.DEBUG),
                    )

            if self.stop_event.is_set():
                self.exit_code = 0
                return self.exit_code

            if self._consume_reconnect_request():
                delay = self.config.reconnect_initial_seconds
                logger.info('Reconnect requested')
                continue

            interrupted = self._wait_for_retry(delay)
            if self.stop_event.is_set():
                self.exit_code = 0
                return self.exit_code
            if interrupted and self._consume_reconnect_request():
                delay = self.config.reconnect_initial_seconds
                logger.info('Reconnect requested')
                continue

            delay = min(
                self.config.reconnect_max_seconds,
                max(self.config.reconnect_initial_seconds, delay * 2),
            )

        self.exit_code = 0
        return self.exit_code
