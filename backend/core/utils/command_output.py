import json
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from core.utils.formatting import format_dict, format_grouped_dict, format_table


OutputShape = Literal['flat', 'table', 'dict', 'grouped_dict']


class OutputFormat(str, Enum):
    TEXT = 'text'
    JSON = 'json'


class ResultDataShape(str, Enum):
    FLAT = 'flat'
    TABLE = 'table'
    GROUPED = 'grouped'
    NUMBERED_LIST = 'numbered_list'


class ResultEventType(str, Enum):
    STARTED = 'started'
    PROGRESS = 'progress'
    CHUNK = 'chunk'
    COMPLETED = 'completed'


class ResultStatus(str, Enum):
    SUCCESS = 'success'
    PARTIAL = 'partial'
    ERROR = 'error'
    CANCELLED = 'cancelled'
    TIMED_OUT = 'timed_out'
    INTERRUPTED = 'interrupted'


def render_result_payload(payload: dict, output_format: str = 'text', *,
                          view: str = 'message', shape: str | None = None,
                          width: int = 20) -> str:
    """Render a caller-selected view; the transport carries no UI instructions.

    For a selected data view, text and --json use precisely the same data.
    A caller may project fields *before* invoking this shared renderer.
    """
    if output_format not in ('text', 'json') or view not in ('message', 'data'):
        raise ValueError('Invalid result presentation')
    if not isinstance(payload, dict):
        raise ValueError('Invalid result payload')
    completed = payload.get('event_type') == ResultEventType.COMPLETED
    failed = completed and payload.get('status') not in (ResultStatus.SUCCESS, ResultStatus.PARTIAL)
    message = str(payload.get('message') or '')
    if failed or view == 'message':
        if output_format == 'json':
            return json.dumps({'status': payload.get('status'), 'message': message},
                              ensure_ascii=False, indent=2) if completed else json.dumps(message, ensure_ascii=False)
        return message
    data = payload.get('data')
    if not isinstance(data, (dict, list)):
        raise ValueError('Structured result requires an object or array')
    if output_format == 'json':
        return json.dumps(data, ensure_ascii=False, indent=2)
    shape = shape or (ResultDataShape.TABLE if isinstance(data, list) else ResultDataShape.FLAT)
    if shape in (ResultDataShape.FLAT, 'dict') and not isinstance(data, dict):
        raise ValueError('Flat view requires an object')
    if shape in (ResultDataShape.TABLE, ResultDataShape.NUMBERED_LIST) and not isinstance(data, list):
        raise ValueError('List view requires an array')
    if shape in (ResultDataShape.GROUPED, 'grouped_dict') and not isinstance(data, dict):
        raise ValueError('Grouped view requires an object')
    if shape == ResultDataShape.NUMBERED_LIST:
        lines = [f'{row["index"]:>3}  {row["command"]}' for row in data]
        return '\n'.join(lines) if lines else message or 'No data to display'
    if data == []:
        return message or 'No data to display'
    if shape == ResultDataShape.TABLE and isinstance(data, list) and data:
        if not isinstance(data[0], dict) or any(
                not isinstance(row, dict) or set(row) != set(data[0]) for row in data):
            return json.dumps(data, ensure_ascii=False, indent=2)
    internal_shape = ('grouped_dict' if shape == ResultDataShape.GROUPED else
                      'dict' if shape == ResultDataShape.FLAT else shape)
    _, text = render_structured_result(StructuredCommandResult(
        status=1, data=data, shape=internal_shape,
        width=width if isinstance(data, dict) else None))
    return text


@dataclass
class StructuredCommandResult:
    status: int
    data: dict | list[dict]
    shape: OutputShape | None = None
    width: int | None = None
    null_text: str | None = None


def parse_output_format(arg: str = '', default: str = 'text') -> str:
    text = str(arg or '').strip()
    if not text:
        return default

    parts = text.split()
    last = parts[-1].lower()
    if last in ('json', '--json'):
        return 'json'

    return default


def strip_output_format_arg(arg: str = '') -> str:
    text = str(arg or '').strip()
    if not text:
        return ''

    parts = text.split()
    last = parts[-1].lower()
    if last in ('json', '--json'):
        return ' '.join(parts[:-1]).strip()

    return text


def render_structured_result(result, output_format: str = 'text'):
    if not isinstance(result, StructuredCommandResult):
        return result

    if output_format == 'json':
        return result.status, json.dumps(result.data, ensure_ascii=False, indent=2)

    data = result.data

    if isinstance(data, dict) and result.shape == 'grouped_dict':
        return result.status, format_grouped_dict(data)

    if isinstance(data, dict):
        if result.width is None:
            raise ValueError('width is required for dict output')
        text_data = ({key: result.null_text if value is None else value
                      for key, value in data.items()} if result.null_text is not None else data)
        return result.status, format_dict(text_data, width=result.width)

    if isinstance(data, list):
        if not data:
            return result.status, 'No data to display'

        headers = [str(header) for header in data[0].keys()]
        rows = []

        for item in data:
            row = []
            for header in headers:
                value = item.get(header, '')
                if value is None:
                    value = ''
                row.append(str(value))
            rows.append(row)

        return result.status, format_table(headers, rows)

    return result.status, str(data)