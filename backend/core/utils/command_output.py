import json
from dataclasses import dataclass, fields
import inspect
from enum import Enum
from typing import Literal, Mapping

from core.utils.formatting import format_dict, format_grouped_dict, format_table


OutputShape = Literal['flat', 'table', 'dict', 'grouped', 'grouped_dict', 'numbered_list', 'lines', 'records', 'key_value']


class OutputFormat(str, Enum):
    TEXT = 'text'
    JSON = 'json'


class ResultDataShape(str, Enum):
    FLAT = 'flat'
    TABLE = 'table'
    GROUPED = 'grouped'
    NUMBERED_LIST = 'numbered_list'
    LINES = 'lines'
    RECORDS = 'records'
    KEY_VALUE = 'kv'


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


# One set of textual layouts is available to Server Builtins and Client ACMD.
PRESENTATION_FORMATS = frozenset((
    'lines', 'table', 'records', 'kv', 'grouped', 'numbered', 'flat', 'json',
))


def resolve_presentation(arguments: Mapping, default_shape: str = ResultDataShape.TABLE,
                         *, allowed_layouts=None) -> tuple[str, str]:
    """Choose serialization and a declared text layout; never infer mapping semantics."""
    requested = str(arguments.get('format') or '').strip().lower()
    if requested and requested not in PRESENTATION_FORMATS:
        raise ValueError(f'Invalid --format: {requested}; choose: {", ".join(sorted(PRESENTATION_FORMATS))}')
    if allowed_layouts is not None and requested and requested not in allowed_layouts and requested != 'json':
        raise ValueError(f'Unsupported --format: {requested}; supported: {", ".join(allowed_layouts)}, json')
    if arguments.get('json') or requested == OutputFormat.JSON:
        return OutputFormat.JSON, default_shape
    if requested:
        return OutputFormat.TEXT, requested
    return OutputFormat.TEXT, default_shape


def _display(value):
    if value is None:
        return ''
    return ', '.join(str(item) for item in value) if isinstance(value, list) else str(value)


def _selected_columns(rows, columns):
    if columns:
        return tuple((str(name), str(header)) for name, header in columns)
    return tuple((str(name), str(name)) for name in rows[0]) if rows else ()


def _present_data(data, shape, *, width=20, null_text=None, columns=(),
                  line_field=None, line_separator='/', key_field=None,
                  value_field=None, key_separator='.', group_field='group', text_values=None, number_field='index',
                  number_value_field='command'):
    """Shared text-layout engine. Selects fields without altering the JSON data."""
    shape = str(shape.value if isinstance(shape, Enum) else (shape or '')).lower()
    if shape == 'dict':
        shape = ResultDataShape.FLAT
    if shape == 'grouped_dict':
        shape = ResultDataShape.GROUPED
    if shape == 'numbered':
        shape = ResultDataShape.NUMBERED_LIST
    if shape == ResultDataShape.FLAT:
        if not isinstance(data, dict):
            raise ValueError('Flat view requires an object')
        if width is None:
            raise ValueError('width is required for dict output')
        values = ({k: null_text if v is None else v for k, v in data.items()}
                  if null_text is not None else data)
        return format_dict(values, width=width)
    if shape == ResultDataShape.GROUPED and isinstance(data, dict):
        if any(not isinstance(value, dict) for value in data.values()):
            raise ValueError('Grouped view requires an object of key-value groups')
        return format_grouped_dict(data)
    if shape == ResultDataShape.KEY_VALUE and isinstance(data, dict):
        return '\n'.join(f'{k} = {_display(v)}' for k, v in data.items())
    if not isinstance(data, list):
        raise ValueError(f'{shape} view requires an array')
    if not data:
        return 'No data to display'
    if any(not isinstance(row, dict) for row in data):
        raise ValueError('List records must be objects')
    selected = _selected_columns(data, columns)

    def require_fields(*fields):
        for field in fields:
            if not field or any(field not in item for item in data):
                raise ValueError(f'{shape} view requires declared field: {field or "<unset>"}')

    def display_item(item, field):
        value = item.get(field, '')
        mapped = (text_values or {}).get(field)
        if mapped is not None:
            value = mapped.get(value, mapped.get(str(value), value))
        return _display(value)

    if shape == ResultDataShape.TABLE:
        if not columns and any(set(item) != set(data[0]) for item in data):
            raise ValueError('Table view requires consistent record fields')
        if selected:
            require_fields(*(field for field, _ in selected))
        headers = [header for _, header in selected]
        rows = [[display_item(item, field) for field, _ in selected] for item in data]
        return format_table(headers, rows)
    if shape == ResultDataShape.RECORDS:
        if selected:
            require_fields(*(field for field, _ in selected))
        return '\n'.join('\n'.join(['---'] + [
            f'{header}: {display_item(item, field).replace(chr(10), chr(10) + "  ")}'
            for field, header in selected]) for item in data)
    if shape == ResultDataShape.LINES:
        fields = (line_field,) if isinstance(line_field, str) else tuple(line_field or ())
        if not fields:
            raise ValueError('Lines view requires an explicitly declared display field')
        require_fields(*fields)
        return '\n'.join(line_separator.join(display_item(item, field) for field in fields) for item in data)
    if shape == ResultDataShape.KEY_VALUE:
        if not key_field or not value_field:
            raise ValueError('Key-value view requires declared key and value fields')
        key_fields = (key_field,) if isinstance(key_field, str) else tuple(key_field)
        require_fields(*key_fields, value_field)
        return '\n'.join(
            f'{key_separator.join(display_item(item, key) for key in key_fields)} = {display_item(item, value_field)}'
            for item in data
        )
    if shape == ResultDataShape.GROUPED:
        if not key_field or not value_field:
            raise ValueError('Grouped list view requires key and value fields')
        require_fields(group_field, key_field, value_field)
        groups = {}
        for item in data:
            group = _display(item[group_field])
            key = _display(item[key_field])
            entries = groups.setdefault(group, {})
            if key in entries:
                raise ValueError(f'Grouped view has duplicate key: {group}/{key}')
            entries[key] = item[value_field]
        return format_grouped_dict(groups)
    if shape == ResultDataShape.NUMBERED_LIST:
        require_fields(number_field, number_value_field)
        if any(isinstance(item[number_field], bool) or not isinstance(item[number_field], int)
               for item in data):
            raise ValueError('Numbered view requires integer identifiers')
        if len({item[number_field] for item in data}) != len(data):
            raise ValueError('Numbered view requires unique identifiers')
        return '\n'.join(f'{item[number_field]:>3}  {_display(item[number_value_field])}'
                         for item in data)
    raise ValueError(f'Unknown result layout: {shape}')


# _present_data's keyword-only signature is the single source of rendering options.
# Both Client presentation declarations and Server projection reuse it.
_LAYOUT_OPTION_NAMES = frozenset(
    name for name, param in inspect.signature(_present_data).parameters.items()
    if param.kind is inspect.Parameter.KEYWORD_ONLY
)


def layout_options(source):
    if isinstance(source, dict):
        return {key: value for key, value in source.items() if key in _LAYOUT_OPTION_NAMES}
    return {key: getattr(source, key) for key in _LAYOUT_OPTION_NAMES}



def render_presented_result(wire):
    """Render an explicit Result presentation without changing the wire event."""
    p = wire['presentation']
    if wire.get('status') not in ('success', 'partial'):
        return wire.get('message') or ''
    selected = p.get('requested') or p['default']
    try:
        if selected == 'message':
            return wire.get('message') or ''
        if selected == 'json':
            return json.dumps(wire['data'], ensure_ascii=False, indent=2)
        visible = _present_data(wire['data'], selected, **layout_options(p))
        if wire['data'] == [] and wire.get('message'):
            return wire['message']
        return visible
    except (ValueError, TypeError, KeyError) as exc:
        return f'[!] Result display failed: {exc}'


def result_visible_text(event):
    """Return Result-defined display text, or None if no complete presentation exists."""
    if not isinstance(event, dict) or event.get('event_type') != 'completed':
        return None
    p = event.get('presentation')
    if not isinstance(p, dict):
        return None
    if p.get('source') == 'data' and 'data' not in event:
        return None
    return render_presented_result(event)


def project_result_output_texts(results):
    """History view of the single saved Result JSON; never saves duplicated text."""
    if not any(isinstance(item, dict) and isinstance(item.get('presentation'), dict)
               for item in results):
        return None
    return [result_visible_text(item) for item in results]


def project_result_events(items):
    """Present structured Results without replacing their execution facts."""
    for item in items:
        visible = result_visible_text(item.event)
        yield item if visible is None else item.with_text(visible)


def render_result_payload(payload: dict, output_format: str = 'text', *,
                          view: str = 'message', shape: str | None = None,
                          width: int = 20, columns=(), line_field=None,
                          line_separator='/', key_field=None, value_field=None, key_separator='.',
                          group_field='group', number_field='index',
                          number_value_field='command', footer='') -> str:
    """Render Result Envelope without changing structured data or the wire payload."""
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
    text = _present_data(data, shape, width=width, columns=columns,
                         line_field=line_field, line_separator=line_separator,
                         key_field=key_field, value_field=value_field, key_separator=key_separator,
                         group_field=group_field, number_field=number_field,
                         number_value_field=number_value_field)
    if data == []:
        text = message or text
    return f'{text}\n\n{footer}' if footer else text


@dataclass
class StructuredCommandResult:
    status: int
    data: dict | list[dict]
    shape: OutputShape | None = None
    width: int | None = None
    null_text: str | None = None
    columns: tuple[tuple[str, str], ...] = ()
    line_field: str | tuple[str, ...] | None = None
    line_separator: str = '/'
    key_field: str | tuple[str, ...] | None = None
    value_field: str | None = None
    key_separator: str = '.'
    group_field: str = 'group'
    number_field: str = 'index'
    number_value_field: str = 'command'
    text_values: dict | None = None
    message: str = ''
    source: str = 'data'
    formats: tuple[str, ...] = ()
    view: dict | None = None

    def as_event(self, *, requested=None):
        """Keep native ACMD facts and the Client-parsed display selection."""
        from core.protocol.result_envelope import ResultEnvelope

        event = ResultEnvelope(
            status=ResultStatus.SUCCESS if self.status == 1 else ResultStatus.ERROR,
            message=self.message, data=self.data,
        ).as_payload()
        if self.source not in ('message', 'data'):
            raise ValueError('Invalid result presentation source')
        default = ('message' if self.source == 'message' else
                   str(self.shape.value if isinstance(self.shape, Enum) else
                       (self.shape or (ResultDataShape.FLAT if isinstance(self.data, dict) else ResultDataShape.TABLE))))
        if default in ('dict', 'key_value', 'numbered_list'):
            default = {'dict': 'flat', 'key_value': 'kv', 'numbered_list': 'numbered'}[default]
        allowed = tuple(self.formats or (default, 'json'))
        if default not in allowed:
            raise ValueError('Result default presentation is not among supported formats')
        hints = {'source': self.source, 'default': default}
        if requested is not None:
            hints['requested'] = requested
        for field in fields(self):
            if field.name not in _LAYOUT_OPTION_NAMES:
                continue
            value = getattr(self, field.name)
            if value is not None and value != field.default:
                hints[field.name] = value
        event['presentation'] = hints
        if self.view is not None:
            event['view'] = self.view
        return event


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


def render_structured_result(result, output_format: str = 'text', *, shape: str | None = None):
    """Render Client ACMD/Shell and Server XT through the same layout engine."""
    if not isinstance(result, StructuredCommandResult):
        return result
    if output_format == 'json':
        return result.status, json.dumps(result.data, ensure_ascii=False, indent=2)
    if output_format != 'text':
        raise ValueError(f'Invalid output format: {output_format}')
    data = result.data
    if not isinstance(data, (dict, list)):
        return result.status, str(data)
    layout = shape or result.shape or (ResultDataShape.FLAT if isinstance(data, dict) else ResultDataShape.TABLE)
    return result.status, _present_data(data, layout, **layout_options(result))
