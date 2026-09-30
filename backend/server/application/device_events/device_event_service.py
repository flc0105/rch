import json
import re
import uuid
from datetime import datetime, timezone


_EVENT_KIND_RE = re.compile(r'^[a-z0-9][a-z0-9_.-]{0,127}$')
_MAX_EVENT_JSON_CHARS = 64 * 1024


class DeviceEventService:
    """Normalize Client-originated events before publishing them to WebEventBus."""

    def __init__(self, *, server, event_bus):
        self.server = server
        self.event_bus = event_bus

    def ingest(self, payload: dict) -> dict:
        source = payload if isinstance(payload, dict) else {}
        client_id = str(source.get('client_id') or '').strip()
        if not client_id:
            raise ValueError('client_id is required')

        session = self.server.get_target_connection_by_client_id(client_id)
        session_info = getattr(session, 'session_info', None)
        hostname = str(getattr(session_info, 'hostname', '') or source.get('hostname') or '').strip()

        kind = str(source.get('kind') or '').strip().lower()
        if not _EVENT_KIND_RE.fullmatch(kind):
            raise ValueError('Invalid device event kind')

        data = source.get('data')
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError('device event data must be an object')

        source_info = source.get('source') if isinstance(source.get('source'), dict) else {}
        normalized_source = {
            'type': str(source_info.get('type') or '').strip()[:64],
            'id': str(source_info.get('id') or '').strip()[:128],
            'name': str(source_info.get('name') or '').strip()[:128],
        }

        event = {
            'schema_version': 1,
            'event_id': str(source.get('event_id') or uuid.uuid4().hex).strip()[:128],
            'client_id': client_id,
            'hostname': hostname,
            'kind': kind,
            'occurred_at': str(source.get('occurred_at') or self._utc_now_iso()).strip()[:64],
            'source': normalized_source,
            'data': data,
        }
        message = str(source.get('message') or '').strip()
        if message:
            event['message'] = message[:1000]

        if len(json.dumps(event, ensure_ascii=False, default=str)) > _MAX_EVENT_JSON_CHARS:
            raise ValueError('device event payload is too large')

        self.event_bus.publish('device_event', event)
        return event

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
