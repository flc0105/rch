"""Canonical execution result facts, independent of Terminal and Web presentation."""
import json
from dataclasses import dataclass
from typing import Any

from core.utils.command_output import ResultEventType, ResultStatus, PRESENTATION_FORMATS


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



def validate_result_view(view: dict) -> None:
    """Validate result-level Viewer metadata independently of transport identity."""
    if not isinstance(view, dict) or set(view) - {'titleField', 'columns', 'details', 'actions'}:
        raise ValueError('Invalid Result view')
    if len(json.dumps(view, ensure_ascii=False)) > 16384:
        raise ValueError('Result view is too large')
    field = view.get('titleField')
    if field is not None and (not isinstance(field, str) or not field or len(field) > 128):
        raise ValueError('Invalid Result view titleField')
    columns = view.get('columns', [])
    details = view.get('details', [])
    actions = view.get('actions', [])
    if not isinstance(columns, list) or len(columns) > 80 or not isinstance(details, list) or len(details) > 80 or not isinstance(actions, list) or len(actions) > 16:
        raise ValueError('Invalid Result view collections')
    for name in details:
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError('Invalid Result view details')
    for column in columns:
        if not isinstance(column, dict) or set(column) - {'field', 'width', 'minWidth'} or not isinstance(column.get('field'), str) or not column['field']:
            raise ValueError('Invalid Result view column')
        for size in ('width', 'minWidth'):
            if size in column and (type(column[size]) is not int or not 40 <= column[size] <= 1600):
                raise ValueError('Invalid Result view column size')
    for action in actions:
        if not isinstance(action, dict) or set(action) - {'label', 'command', 'confirm', 'refresh'}:
            raise ValueError('Invalid Result view action')
        if not isinstance(action.get('label'), str) or not 1 <= len(action['label']) <= 80 or not isinstance(action.get('command'), str) or not 1 <= len(action['command']) <= 2048:
            raise ValueError('Invalid Result view action text')
        if any(key in action and type(action[key]) is not bool for key in ('confirm', 'refresh')):
            raise ValueError('Invalid Result view action flag')



def build_result_wire_event(request_id, event: dict, *, cwd=None) -> dict:
    """Validate and attach request identity to a typed Result event."""
    from core.protocol.message_types import MSG_TYPE_RESULT
    from core.utils.output_marker import OUTPUT_MARKERS

    if not isinstance(event, dict):
        raise TypeError('Result event must be an object')
    phase = event.get('event_type')
    if phase not in ResultEventType._value2member_map_:
        raise ValueError('Invalid Result event_type')
    if phase == ResultEventType.COMPLETED:
        if event.get('status') not in ResultStatus._value2member_map_:
            raise ValueError('Invalid final Result status')
    elif 'status' in event:
        raise ValueError('Only completed Result may carry status')
    if 'level' in event and (phase != ResultEventType.PROGRESS or
                             event['level'] not in OUTPUT_MARKERS):
        raise ValueError('Only progress accepts an info/success/warning/error level')
    if 'message' in event and not isinstance(event['message'], str):
        raise ValueError('Result message must be text')
    if 'data' in event and not isinstance(event['data'], (dict, list)):
        raise ValueError('Result data must be an object or array')
    if 'presentation' in event and not isinstance(event['presentation'], dict):
        raise ValueError('Result presentation hints must be an object')
    if 'references' in event and (not isinstance(event['references'], list) or
                                  any(not isinstance(item, dict) for item in event['references'])):
        raise ValueError('Invalid Result references')
    if 'presentation' in event:
        p = event['presentation']
        if not isinstance(p, dict) or p.get('source') not in ('message', 'data'):
            raise ValueError('Invalid Result presentation source')
        if p.get('default') not in (PRESENTATION_FORMATS | {'message'}):
            raise ValueError('Invalid Result default presentation')
        if 'requested' in p and p['requested'] not in PRESENTATION_FORMATS:
            raise ValueError('Invalid Result requested presentation')
        if p['source'] == 'data' and 'data' not in event:
            raise ValueError('Data presentation requires Result data')
    if 'view' in event:
        validate_result_view(event['view'])
    packet = {'type': MSG_TYPE_RESULT, 'id': request_id, 'event_type': phase}
    if cwd is not None:
        packet['cwd'] = cwd
    for key in ('status', 'message', 'level', 'data', 'references', 'action', 'presentation', 'view'):
        if key in event:
            packet[key] = event[key]
    return packet


def result_wire_event(request_id, status, result, *, final=True, cwd=None, event_type=None):
    """Normalize an execution result to the single Client/Server wire shape.

    Ordinary commands remain message-only. ACMD/Control/SDK explicitly
    structured results retain native data and references. The wire carries no
    eof or Server-selected output format.
    """
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
    packet = {'event_type': phase}
    if explicit:
        for key in ('message', 'level', 'data', 'references', 'action', 'presentation', 'view'):
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
    return build_result_wire_event(request_id, packet, cwd=cwd)
