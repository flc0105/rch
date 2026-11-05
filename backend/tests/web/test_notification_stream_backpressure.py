from types import SimpleNamespace

from flask import Flask

from server.web.event_bus import WebEventBus
from server.web.routes.notification_stream import create_notification_stream_blueprint


def test_sse_stream_closes_when_sync_subscriber_backlog_overflows():
    bus = WebEventBus()
    service = SimpleNamespace(
        event_bus=bus,
        notification_history_api=SimpleNamespace(get_notifications_after=lambda _event_id: {}),
        notification_preferences_api=SimpleNamespace(is_delivery_enabled=lambda _key: True),
    )
    server = SimpleNamespace(web_service=service)
    app = Flask(__name__)
    app.register_blueprint(create_notification_stream_blueprint(server))

    response = app.test_client().get('/api/notifications/stream', buffered=False)
    stream = iter(response.response)
    try:
        assert b'retry: 3000' in next(stream)
        for number in range(bus.DEFAULT_MAX_PENDING + 1):
            bus.publish('notification_center_updated', {'action': 'added', 'notification': {'id': str(number)}})
        try:
            next(stream)
        except StopIteration:
            pass
        else:
            raise AssertionError('SSE stream should close after its bounded queue overflows')
    finally:
        response.close()
