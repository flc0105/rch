import json
import queue
from datetime import datetime

from flask import Blueprint, Response, request, stream_with_context


def _encode_sse(event_type: str, data: dict, event_id: str = '') -> str:
    lines = []
    normalized_id = str(event_id or '').strip()
    if normalized_id:
        lines.append(f'id: {normalized_id}')
    lines.append(f'event: {str(event_type or "message").strip() or "message"}')
    payload = json.dumps(data if isinstance(data, dict) else {}, ensure_ascii=False, separators=(',', ':'))
    for line in payload.splitlines() or ['{}']:
        lines.append(f'data: {line}')
    return '\n'.join(lines) + '\n\n'


def create_notification_stream_blueprint(server_instance):
    blueprint = Blueprint('notification_stream', __name__)
    web_service = server_instance.web_service
    notification_api = web_service.notification_history_api
    notification_preferences_api = web_service.notification_preferences_api
    event_bus = web_service.event_bus

    @blueprint.get('/api/notifications/stream')
    def stream_notifications():
        last_event_id = str(
            request.headers.get('Last-Event-ID')
            or request.args.get('last_event_id')
            or ''
        ).strip()
        q = event_bus.subscribe(event_types={'notification_center_updated'})

        def encode_delivery(notification: dict, notification_id: str) -> str:
            notification_key = str(notification.get('notification_key') or '').strip()
            if notification_preferences_api.is_delivery_enabled(notification_key):
                return _encode_sse('notification', notification, notification_id)
            # Advance the durable SSE cursor even when this notification is muted.
            # Otherwise a later reconnect would replay an old muted record after
            # the user changed preferences.
            return _encode_sse('cursor', {
                'notification_id': notification_id,
                'notification_key': notification_key,
                'reason': 'disabled_by_preference',
            }, notification_id)

        def event_stream():
            replayed_ids = set()
            try:
                # Tell generic SSE clients how long to wait before reconnecting.
                yield 'retry: 3000\n\n'

                if last_event_id:
                    replay = notification_api.get_notifications_after(last_event_id)
                    if not bool(replay.get('cursor_found')):
                        yield _encode_sse('reset', {
                            'reason': 'cursor_not_found',
                            'last_event_id': last_event_id,
                        })
                    else:
                        for notification in replay.get('notifications') or []:
                            notification_id = str(notification.get('id') or '').strip()
                            if not notification_id:
                                continue
                            replayed_ids.add(notification_id)
                            yield encode_delivery(notification, notification_id)

                while True:
                    try:
                        item = q.get(timeout=15)
                    except queue.Empty:
                        yield _encode_sse('ping', {'time': datetime.now().isoformat()})
                        continue

                    data = item.get('data') if isinstance(item, dict) else None
                    data = data if isinstance(data, dict) else {}
                    if str(data.get('action') or '').strip() != 'added':
                        continue

                    notification = data.get('notification')
                    if not isinstance(notification, dict):
                        continue
                    notification_id = str(notification.get('id') or '').strip()
                    if not notification_id:
                        continue

                    # A notification created after subscription but before the replay
                    # query can be present in both SQLite replay and the live queue.
                    if notification_id in replayed_ids:
                        replayed_ids.discard(notification_id)
                        continue

                    yield encode_delivery(notification, notification_id)
            finally:
                event_bus.unsubscribe(q)

        return Response(
            stream_with_context(event_stream()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
            },
        )

    return blueprint
