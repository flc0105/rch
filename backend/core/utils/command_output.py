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


class ResultDisplay(str, Enum):
    MESSAGE = 'message'
    DATA = 'data'


class ResultEventType(str, Enum):
    CHUNK = 'chunk'
    COMPLETED = 'completed'


def render_result_payload(payload: dict, output_format: str = 'text') -> str:
    """Present a declared result, never infer its intent from data presence."""
    if payload.get('display') not in (ResultDisplay.MESSAGE, ResultDisplay.DATA):
        raise ValueError('Invalid result display')
    if output_format not in ('text', 'json'):
        raise ValueError('Invalid result output format')
    completed = payload.get('event_type') == ResultEventType.COMPLETED
    failed = completed and payload.get('status') != 'success'
    if output_format == 'json':
        if payload['display'] == ResultDisplay.DATA and not failed:
            return json.dumps(payload.get('data'), ensure_ascii=False, indent=2)
        if not completed:
            return json.dumps(payload.get('message') or '', ensure_ascii=False, indent=2)
        return json.dumps({'status': payload['status'], 'message': payload['message']},
                          ensure_ascii=False, indent=2)
    if failed or payload['display'] == ResultDisplay.MESSAGE:
        return str(payload.get('message') or '')
    data = payload.get('data')
    if not isinstance(data, (dict, list)):
        raise ValueError('Structured result requires an object or array')
    shape = payload.get('shape')
    if shape not in (ResultDataShape.FLAT, ResultDataShape.TABLE, 'dict', 'grouped_dict', None):
        raise ValueError('Invalid structured result shape')
    if shape == ResultDataShape.TABLE and not isinstance(data, list):
        raise ValueError('Table result requires an array')
    if shape == ResultDataShape.FLAT and not isinstance(data, dict):
        raise ValueError('Flat result requires an object')
    if data == []:
        return str(payload.get('message') or 'No data to display')
    # The existing table renderer assumes every row has exactly the first
    # row's fields. A general JSON array must not silently drop extra data.
    if isinstance(data, list) and data:
        if not isinstance(data[0], dict) or any(
                not isinstance(row, dict) or set(row) != set(data[0]) for row in data):
            return json.dumps(data, ensure_ascii=False, indent=2)
    _, text = render_structured_result(StructuredCommandResult(
        status=1, data=data, shape='dict' if shape == ResultDataShape.FLAT else shape,
        width=(payload.get('width') or 20) if isinstance(data, dict) else None))
    return text


@dataclass
class StructuredCommandResult:
    status: int
    data: dict | list[dict]
    shape: OutputShape | None = None
    width: int | None = None


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
        return result.status, format_dict(data, width=result.width)

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