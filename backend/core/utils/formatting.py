import sys
import time
from datetime import datetime, timezone
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

    if not index:
        return '\n'.join(f'{key:{width}}{value}' for key, value in data.items())

    return '\n'.join(
        f'{i:<5}{key:{width}}{value}'
        for i, (key, value) in enumerate(data.items())
    )


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


def draw_progress_bar(progress: int, total: int, bar_len: int = 50) -> None:
    if total <= 0:
        return

    completed = int(bar_len * progress / total)
    percent = round(100 * progress / total)
    bar = '=' * completed
    spaces = '-' * (bar_len - completed)

    sys.stdout.write(f'\r[{bar}{spaces}] {percent} %')
    sys.stdout.flush()

    if progress >= total:
        sys.stdout.write('\n')


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


def format_table(headers: Iterable[Any], data: Iterable[Iterable[Any]]) -> str:
    """
    将表格数据格式化为字符串并返回，而不是直接打印
    """
    headers = list(headers)
    rows = [list(row) for row in data]

    if not headers:
        return "No headers to display"

    if not rows:
        return "No data to display"

    column_count = len(headers)
    rows = [row for row in rows if len(row) == column_count]
    if not rows:
        return "Table rows do not match header count"

    column_widths = [
        max(len(str(headers[i])), *(len(str(row[i])) for row in rows))
        for i in range(column_count)
    ]

    row_format = " | ".join(f"{{:<{width}}}" for width in column_widths)

    lines = []
    lines.append(row_format.format(*headers))
    lines.append("-" * (sum(column_widths) + 3 * (column_count - 1)))

    for row in rows:
        lines.append(row_format.format(*row))

    return "\n".join(lines)


def seconds_to_readable_text(seconds):
    try:
        seconds = int(seconds)
    except Exception:
        return None

    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
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
