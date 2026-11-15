"""Result facts used by builtins that execute another command."""
import json

from core.protocol.message_queue import result_terminal_status
from core.utils.command_output import ResultEventType


def inner_result_event(item):
    event = getattr(item, 'event', None)
    if isinstance(event, dict) and event.get('event_type') in ResultEventType._value2member_map_:
        return event
    result = item[1] if len(item) > 1 else None
    if isinstance(result, dict) and result.get('event_type') in ResultEventType._value2member_map_:
        return result
    return None


def inner_terminal_status(item):
    """A chunk/stderr never determines final execution status."""
    event = inner_result_event(item)
    if event is not None:
        if event['event_type'] == ResultEventType.COMPLETED:
            return result_terminal_status(item[0], event)
        return None
    if getattr(item, 'eof', False):
        return result_terminal_status(item[0], item[1])
    return None


def inner_output_text(item):
    """Project a nested command's visible output into a saved text artifact."""
    # An already-rendered CLI view is the actual visible output to save;
    # the raw event may carry additional Web-only business fields.
    presented = item[1] if len(item) > 1 else None
    if isinstance(presented, str):
        return presented
    result = inner_result_event(item)
    if result is None:
        result = presented
    if isinstance(result, dict):
        if result.get('event_type') in (ResultEventType.STARTED,):
            return ''
        message = result.get('message') or result.get('text')
        if message is not None:
            return str(message)
        if 'data' in result:
            return json.dumps(result['data'], ensure_ascii=False, indent=2)
        return json.dumps(result, ensure_ascii=False, indent=2)
    if isinstance(result, list):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return '' if result is None else str(result)
