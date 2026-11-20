"""Portable ACMD inspection commands."""
import json
import os
import tarfile
import zipfile
from contextlib import closing
from pathlib import Path

from client.commands.acmd.decorators import argument_command
from client.commands.acmd.standalone.drives import drives
from client.commands.acmd.standalone.python_packages import python_packages
from core.command_completion.models import CompletionSpec
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, render_structured_result
from core.utils.formatting import format_bytes, format_dict, format_table, get_size


SQLITE_QUERY_SPEC = ArgumentCommandSpec(
    name='sqlite_query',
    description='Read-only SQLite query',
    options=[
        ArgumentOptionSpec('db', 'str', required=True, allow_empty=False, help_text='Database file path',
                           completion=CompletionSpec('filesystem', ('file', 'directory'))),
        ArgumentOptionSpec('query', 'str', required=True, allow_empty=False, help_text='SQL query'),
        ArgumentOptionSpec('limit', 'int', help_text='Maximum result rows (default: unlimited)'),
        ArgumentOptionSpec('json', 'flag', default=False, help_text='Output as JSON'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd sqlite_query --db ./data.db --query "PRAGMA table_list;"'],
)

IMAGE_INFO_SPEC = ArgumentCommandSpec(
    name='image_info',
    description='Show image metadata',
    options=[
        ArgumentOptionSpec('path', 'str', required=True, allow_empty=False, positional_index=0, help_text='Image file path',
                           completion=CompletionSpec('filesystem', ('file', 'directory'))),
        ArgumentOptionSpec('json', 'flag', default=False, help_text='Output as JSON'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)

ARCHIVE_PEEK_SPEC = ArgumentCommandSpec(
    name='archive_peek',
    description='List archive contents without extracting',
    options=[
        ArgumentOptionSpec('path', 'str', required=True, allow_empty=False, positional_index=0, help_text='ZIP or TAR archive path',
                           completion=CompletionSpec('filesystem', ('file', 'directory'))),
        ArgumentOptionSpec('limit', 'int', default=50, help_text='Limit the number of archive entries previewed'),
        ArgumentOptionSpec('json', 'flag', default=False, help_text='Output as JSON'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)


@argument_command('sqlite_query', spec=SQLITE_QUERY_SPEC)
def sqlite_query(self, args_dict):
    limit = args_dict.get('limit')
    if limit is not None and limit < 1:
        return 0, '--limit must be positive'
    try:
        import sqlite3
    except ImportError:
        return 0, 'SQLite is unavailable in this Client Python runtime'

    try:
        path = Path(self.path_resolver.require_existing_file(args_dict['db']))
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            # Do not let SQL open another database or disable query_only.
            conn.set_authorizer(
                lambda action, name, value, _database, _source: sqlite3.SQLITE_DENY
                if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) or (
                    action == sqlite3.SQLITE_PRAGMA and (name or '').lower() == 'query_only'
                    and value is not None
                ) else sqlite3.SQLITE_OK
            )
            cursor = conn.execute(args_dict['query'])
            rows = cursor.fetchall() if limit is None else cursor.fetchmany(limit)
            if args_dict['json']:
                return 1, json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2, default=str)
            if not rows:
                return 1, 'No results'
            return 1, format_table(rows[0].keys(), rows)
    except (OSError, sqlite3.Error, ValueError, OverflowError) as exc:
        return 0, f'Query failed: {exc}'
@argument_command('image_info', spec=IMAGE_INFO_SPEC)
def image_info(self, args_dict):
    try:
        from PIL import Image
    except ImportError:
        return 0, 'Image info requires Pillow on this Client'

    try:
        path = self.path_resolver.require_existing_file(args_dict['path'])
        exif_tags = {
            271: 'make', 272: 'model', 42036: 'lens_model', 33434: 'exposure_time',
            33437: 'f_number', 34855: 'iso', 36867: 'datetime_original',
            37386: 'focal_length', 305: 'software', 37510: 'user_comment',
            40961: 'color_space',
        }
        with Image.open(path) as image:
            info = {
                'path': args_dict['path'],
                'width': image.width,
                'height': image.height,
                'size': f'{image.width}x{image.height}',
                'format': image.format,
                'mode': image.mode,
                'file_size': get_size(os.path.getsize(path)),
            }
            # Pillow's JPEG accessor merges the main and EXIF IFDs.
            exif = image._getexif() if hasattr(image, '_getexif') else image.getexif()
            for tag, value in (exif or {}).items():
                key = exif_tags.get(tag)
                if not key:
                    continue
                if tag == 40961:
                    value = 'sRGB' if value == 1 else 'Uncalibrated'
                elif isinstance(value, bytes):
                    value = value.decode('utf-8', errors='replace')
                elif hasattr(value, 'numerator') and hasattr(value, 'denominator') and not isinstance(value, int):
                    value = (int(value.numerator) if value.denominator == 1 else
                             float(value) if value.denominator else str(value))
                info[key] = value
        if args_dict['json']:
            return 1, json.dumps(info, ensure_ascii=False, indent=2, default=str)
        return 1, format_dict(info, width=30)
    except (OSError, ValueError) as exc:
        return 0, f'Failed to get image info: {exc}'
@argument_command('archive_peek', spec=ARCHIVE_PEEK_SPEC)
def archive_peek(self, args_dict):
    limit = args_dict['limit']
    try:
        path = self.path_resolver.require_existing_file(args_dict['path'])
        preview = self.archive_service.inspect_archive(path, entry_limit=limit)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return 0, f'Failed to peek archive: {exc}'
    if args_dict['json']:
        # Build the CLI tree from shared preview nodes without exposing Browser fields.
        tree = []
        pending = [(preview['tree'], tree)]
        while pending:
            source, target = pending.pop()
            for node in source:
                item = {'name': node['name']}
                if node['is_dir']:
                    item['children'] = []
                    pending.append((node['children'], item['children']))
                else:
                    item['size'] = format_bytes(node['size'])
                target.append(item)
        data = {
            'name': preview['name'],
            'archive_size': format_bytes(preview['archive_size']),
            'tree': tree,
        }
        if preview['truncated']:
            data['truncated'] = True
        return render_structured_result(StructuredCommandResult(status=1, data=data), output_format='json')

    if not preview['tree']:
        return 1, 'Archive is empty' if not preview['truncated'] else f'No files in first {limit} entries'
    lines = [f"{preview['name']} ({format_bytes(preview['archive_size'])})"]
    pending = [(iter(enumerate(preview['tree'])), len(preview['tree']), '')]
    while pending:
        siblings, count, prefix = pending[-1]
        entry = next(siblings, None)
        if entry is None:
            pending.pop()
            continue
        index, node = entry
        last = index == count - 1
        branch = '└── ' if last else '├── '
        name = node['name']
        detail = '/' if node['is_dir'] else f" ({format_bytes(node['size'])})"
        lines.append(f'{prefix}{branch}{name}{detail}')
        children = node['children']
        if children:
            pending.append((iter(enumerate(children)), len(children), prefix + ('    ' if last else '│   ')))
    if preview['truncated']:
        lines.append(f'... and more (limited to {limit})')
    return 1, '\n'.join(lines)


def register_commands(registry):
    """Register declarations owned by this Common / Platform module."""
    registry.register(drives)
    registry.register(python_packages)
    registry.register(sqlite_query)
    registry.register(image_info)
    registry.register(archive_peek)
