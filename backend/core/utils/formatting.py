import time
from datetime import datetime, timezone
import unicodedata
from typing import Any, Iterable, Mapping


class TimeFormatter:
    @staticmethod
    def compact_now() -> str:
        return time.strftime('%Y%m%d-%H%M%S')

    @staticmethod
    def readable_now() -> str:
        return time.strftime('%Y-%m-%d %H:%M:%S')


def get_time() -> str:
    return TimeFormatter.compact_now()


def get_readable_time() -> str:
    return TimeFormatter.readable_now()


def format_dict(data: Mapping[str, Any], width: int = 15, index: bool = False) -> str:
    if not data:
        return ''

    def display(value):
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return ', '.join(value)
        return str(value)

    if not index:
        return '\n'.join(f'{key:{width}}{display(value)}' for key, value in data.items())

    return '\n'.join(
        f'{i:<5}{key:{width}}{display(value)}'
        for i, (key, value) in enumerate(data.items())
    )


def format_grouped_dict(data: Mapping[str, Mapping[str, Any]]) -> str:
    """Render two-level command data as [group] followed by key = value lines."""
    sections = []
    for group, fields in data.items():
        if not isinstance(fields, Mapping):
            raise ValueError('grouped dict sections must be mappings')
        lines = [f'[{group}]']
        for key, value in fields.items():
            if isinstance(value, Mapping):
                raise ValueError('grouped dict fields cannot contain nested mappings')
            lines.append(f'{key} = {value}')
        sections.append('\n'.join(lines))
    return '\n\n'.join(sections)


def get_size(size_in_bytes: float, suffix: str = "B") -> str:
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if size_in_bytes < factor:
            return f"{size_in_bytes:.2f}{unit}{suffix}"
        size_in_bytes /= factor
    return f"{size_in_bytes:.2f}E{suffix}"


def format_bytes(
        size_in_bytes,
        *,
        decimals: int = 2,
        trim_trailing_zeros: bool = True,
        separator: str = ' ',
        unit_decimals: Mapping[str, int] | None = None,
        max_unit: str = 'PB',
) -> str:
    """Format byte counts for human-facing output with configurable precision."""
    try:
        size = max(float(size_in_bytes or 0), 0.0)
    except (TypeError, ValueError):
        size = 0.0

    units = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB')
    try:
        max_index = units.index(str(max_unit or 'PB').upper())
    except ValueError:
        max_index = units.index('PB')

    unit_index = 0
    while size >= 1024 and unit_index < max_index:
        size /= 1024.0
        unit_index += 1

    unit = units[unit_index]
    precision = 0 if unit_index == 0 else max(0, int(decimals))
    if unit_decimals and unit in unit_decimals:
        precision = max(0, int(unit_decimals[unit]))

    if precision == 0:
        text = str(int(round(size)))
    else:
        text = f'{size:.{precision}f}'
        if trim_trailing_zeros:
            text = text.rstrip('0').rstrip('.')

    return f'{text}{separator}{unit}'


def format_bytes_precise(size_in_bytes) -> str:
    """Legacy detailed storage display: B=0dp, KB=1dp, MB/GB=2dp."""
    return format_bytes(
        size_in_bytes,
        unit_decimals={'B': 0, 'KB': 1, 'MB': 2, 'GB': 2},
        trim_trailing_zeros=False,
        max_unit='GB',
    )


def print_table(headers: Iterable[Any], data: Iterable[Iterable[Any]]) -> None:
    headers = list(headers)
    rows = [list(row) for row in data]

    if not headers:
        print("No headers to display")
        return

    if not rows:
        print("No data to display")
        return

    column_count = len(headers)
    rows = [row for row in rows if len(row) == column_count]
    if not rows:
        print("Table rows do not match header count")
        return

    column_widths = [
        max(len(str(headers[i])), *(len(str(row[i])) for row in rows))
        for i in range(column_count)
    ]

    row_format = " | ".join(f"{{:<{width}}}" for width in column_widths)

    print("\n" + row_format.format(*headers))
    print("-" * (sum(column_widths) + 3 * (column_count - 1)))

    for row in rows:
        print(row_format.format(*row))
    print()


def _cell_display_width(text: str) -> int:
    """Measure terminal columns, including common full-width and combining characters."""
    return sum(
        0 if unicodedata.combining(char) or unicodedata.category(char) in ('Cc', 'Cf')
        else 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        for char in text
    )


def _wrap_table_cell(text: str, width: int) -> list[str]:
    """Wrap without dropping characters, preserving explicit line breaks."""
    result = []
    for source_line in text.split('\n'):
        segment = ''
        used = 0
        for char in source_line:
            size = _cell_display_width(char)
            if segment and used + size > width:
                result.append(segment)
                segment = ''
                used = 0
            segment += char
            used += size
        result.append(segment)
    return result


def format_table(
    headers: Iterable[Any], data: Iterable[Iterable[Any]], *, max_cell_width: int = 72,
) -> str:
    """Render aligned text columns, wrapping overlong cells without truncation."""
    headers = [str(value) for value in headers]
    rows = [list(row) for row in data]

    if not headers:
        return "No headers to display"
    if not rows:
        return "No data to display"

    column_count = len(headers)
    rows = [row for row in rows if len(row) == column_count]
    if not rows:
        return "Table rows do not match header count"

    if max_cell_width < 1:
        raise ValueError('max_cell_width must be positive')

    string_rows = [[str(value) for value in row] for row in rows]
    column_widths = [
        min(max_cell_width, max(
            _cell_display_width(line)
            for cell in [headers[i], *(row[i] for row in string_rows)]
            for line in cell.split('\n')
        ))
        for i in range(column_count)
    ]

    def render_row(cells: list[str]) -> list[str]:
        wrapped = [_wrap_table_cell(value, column_widths[i]) for i, value in enumerate(cells)]
        height = max(len(parts) for parts in wrapped)
        output = []
        for line_no in range(height):
            parts = []
            for i, cell_lines in enumerate(wrapped):
                text = cell_lines[line_no] if line_no < len(cell_lines) else ''
                parts.append(text + ' ' * (column_widths[i] - _cell_display_width(text)))
            output.append(' | '.join(parts))
        return output

    lines = render_row(headers)
    lines.append('-' * (sum(column_widths) + 3 * (column_count - 1)))
    for row in string_rows:
        lines.extend(render_row(row))
    return '\n'.join(lines)


def seconds_to_readable_text(seconds, *, compact=False):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError, OverflowError):
        return None

    days, rem = divmod(max(seconds, 0), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if compact:
        parts = ((days, 'd'), (hours, 'h'), (minutes, 'm'), (seconds, 's'))
        first = next((i for i, (value, _) in enumerate(parts) if value), 3)
        return ' '.join(f'{value}{unit}' for value, unit in parts[first:])
    return f"{days}d {hours}h {minutes}m {seconds}s"


def timestamp_to_readable_time(timestamp):
    """
    将 Unix 时间戳（秒）转换为本地可读时间。

    参数:
        timestamp: int 或 float，Unix 时间戳（秒）

    返回:
        str，格式如 '2026-04-23 14:32:15'
    """
    dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    dt_local = dt_utc.astimezone()
    return dt_local.strftime('%Y-%m-%d %H:%M:%S')
