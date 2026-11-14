"""Canonical execution result facts, independent of Terminal and Web presentation."""
from dataclasses import dataclass
from typing import Any

from core.utils.command_output import ResultEventType, ResultStatus


@dataclass(frozen=True)
class ResultEnvelope:
    status: str = ResultStatus.SUCCESS
    message: str = ''
    data: Any = None
    references: list[dict] | None = None

    def as_payload(self) -> dict:
        if self.status not in ResultStatus._value2member_map_ or not isinstance(self.message, str):
            raise ValueError('Invalid result status or message')
        payload = {'event_type': ResultEventType.COMPLETED,
                   'status': self.status, 'message': self.message}
        if self.data is not None:
            if not isinstance(self.data, (dict, list)):
                raise ValueError('Result data must be an object or array')
            payload['data'] = self.data
        if self.references is not None:
            if not isinstance(self.references, list) or any(not isinstance(ref, dict) for ref in self.references):
                raise ValueError('Invalid result references')
            payload['references'] = self.references
        return payload


def result_wire_event(request_id, status, result, *, final=True, cwd=None, event_type=None):
    """Normalize an execution result to the single Client/Server wire shape.

    Ordinary commands remain message-only; explicitly structured Control/SDK
    results retain data and references. The wire contains no eof or display.
    """
    from core.protocol.message_types import MSG_TYPE_RESULT

    explicit = result if isinstance(result, dict) and result.get('event_type') in (
        ResultEventType.CHUNK, ResultEventType.PROGRESS, ResultEventType.COMPLETED,
        'error', 'cancelled') else None
    # The sender's final flag is the sole source of terminality. An
    # intermediate payload cannot prematurely finish another request.
    phase = (ResultEventType.COMPLETED if final else
             (event_type or (explicit.get('event_type') if explicit else None)))
    if not final and phase == ResultEventType.COMPLETED:
        phase = ResultEventType.CHUNK
    if phase not in (ResultEventType.STARTED, ResultEventType.CHUNK, ResultEventType.PROGRESS, ResultEventType.COMPLETED):
        phase = ResultEventType.COMPLETED if final else ResultEventType.CHUNK
    packet = {'type': MSG_TYPE_RESULT, 'id': request_id, 'event_type': phase}
    if cwd is not None:
        packet['cwd'] = cwd
    if explicit:
        for key in ('message', 'data', 'references', 'action'):
            if key in explicit:
                packet[key] = explicit[key]
        if 'message' not in packet and isinstance(explicit.get('text'), str):
            packet['message'] = explicit['text']
    elif isinstance(result, (dict, list)):
        packet['data'] = result
    else:
        packet['message'] = '' if result is None else str(result)
    if phase == ResultEventType.COMPLETED:
        reason = (explicit or {}).get('failure_reason')
        target_status = (explicit or {}).get('status')
        if reason in ('cancelled', 'timed_out', 'interrupted'):
            target_status = reason
        elif (explicit or {}).get('event_type') == 'cancelled':
            target_status = 'cancelled'
        elif target_status not in ResultStatus._value2member_map_:
            target_status = 'success' if status == 1 else 'error'
        if status != 1 and target_status == 'success':
            target_status = 'error'
        packet['status'] = target_status
    return packet
