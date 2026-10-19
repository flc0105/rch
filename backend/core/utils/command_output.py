import json
from dataclasses import dataclass
from typing import Literal

from core.utils.formatting import format_dict, format_grouped_dict, format_table


OutputShape = Literal['dict', 'grouped_dict', 'table']


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