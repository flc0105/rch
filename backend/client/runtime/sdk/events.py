from datetime import datetime, timezone
import uuid

from client.http.client_api import ClientApiClient
from client.runtime.sdk import context


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _build_source(script_context: dict) -> dict:
    source_type = _safe_text(script_context.get('source_type'))
    source_id = _safe_text(script_context.get('source_id'))
    source_name = _safe_text(script_context.get('source_name'))

    if not source_type:
        source_type = 'script' if context.script_name() else 'sdk'
    if not source_id:
        source_id = _safe_text(script_context.get('job_id'))
    if not source_name:
        source_name = (
            _safe_text(script_context.get('job_key'))
            or _safe_text(script_context.get('job_name'))
            or context.script_name()
        )

    return {
        'type': source_type,
        'id': source_id,
        'name': source_name,
    }


def emit(kind: str, data: dict | None = None, message: str = '') -> dict:
    """Emit a generic device event through the RCH Server.

    The transport is intentionally shared by scripts, Background Jobs, and future
    client-side rules/alerts. Callers describe what happened; the Server decides
    how the event is projected into browser notifications.
    """
    normalized_kind = _safe_text(kind).lower()
    if not normalized_kind:
        raise ValueError('event kind is required')
    if data is not None and not isinstance(data, dict):
        raise ValueError('event data must be an object')

    client_id = context.client_id()
    if not client_id:
        raise RuntimeError('events.emit() requires an active Script SDK client context')

    script_context = context.get_script_context()
    payload = {
        'schema_version': 1,
        'event_id': uuid.uuid4().hex,
        'client_id': client_id,
        'hostname': context.hostname(),
        'kind': normalized_kind,
        'occurred_at': _utc_now_iso(),
        'source': _build_source(script_context),
        'data': dict(data or {}),
    }

    normalized_message = _safe_text(message)
    if normalized_message:
        payload['message'] = normalized_message

    return ClientApiClient().post_device_event(payload, timeout=10)
