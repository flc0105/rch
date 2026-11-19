"""Portable ACMD inspection commands."""
import importlib
import importlib.metadata
import json
import os
import tarfile
import time
import zipfile
from contextlib import closing
from itertools import islice
from pathlib import Path

from client.commands.acmd.decorators import argument_command
from core.command_completion.models import CompletionSpec
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.formatting import format_dict, format_table, get_size


SQLITE_QUERY_SPEC = ArgumentCommandSpec(
    name='sqlite_query',
    description='Read-only SQLite query',
    options=[
        ArgumentOptionSpec('db', 'str', required=True, allow_empty=False, help_text='Database file path',
                           completion=CompletionSpec('filesystem', ('file', 'directory'))),
        ArgumentOptionSpec('query', 'str', required=True, allow_empty=False, help_text='SQL query'),
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

IMPORT_CHECK_SPEC = ArgumentCommandSpec(
    name='import_check',
    description='Check Python package/module status',
    options=[
        ArgumentOptionSpec('module', 'str', required=True, allow_empty=False, positional_index=0, help_text='Module name'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)

ARCHIVE_PEEK_SPEC = ArgumentCommandSpec(
    name='archive_peek',
    description='List archive contents without extracting',
    options=[
        ArgumentOptionSpec('path', 'str', required=True, allow_empty=False, positional_index=0, help_text='ZIP or TAR archive path',
                           completion=CompletionSpec('filesystem', ('file', 'directory'))),
        ArgumentOptionSpec('limit', 'int', default=50, help_text='Limit number of entries'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
)


class ACMDInspectionCommands:
    @argument_command('sqlite_query', spec=SQLITE_QUERY_SPEC)
    def sqlite_query(self, args_dict):
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
                if args_dict['json']:
                    rows = [dict(row) for row in cursor]
                    return 1, json.dumps(rows, ensure_ascii=False, indent=2, default=str)
                rows = cursor.fetchmany(100)
                if not rows:
                    return 1, 'No results'
                return 1, format_table(rows[0].keys(), rows)
        except (OSError, sqlite3.Error, ValueError) as exc:
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

    @argument_command('import_check', spec=IMPORT_CHECK_SPEC)
    def import_check(self, args_dict):
        name = args_dict['module'].strip()
        result = {
            'module': name,
            'importable': False,
            'module_path': None,
            'module_version': None,
            'package_name': None,
            'package_version': None,
            'package_dependencies': [],
        }
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            result['error'] = str(exc)
            return 1, format_dict(result, width=24)

        result['importable'] = True
        result['module_path'] = getattr(module, '__file__', None)
        for attr in ('__version__', 'version', 'VERSION'):
            if hasattr(module, attr):
                result['module_version'] = str(getattr(module, attr))
                break

        # Pythonista/system modules may have no distribution metadata.
        candidates = importlib.metadata.packages_distributions().get(name.split('.', 1)[0], [])
        if len(candidates) == 1:
            dist = importlib.metadata.distribution(candidates[0])
            result.update(package_name=dist.metadata['Name'], package_version=dist.version,
                          package_dependencies=list(dist.requires or ()))
        return 1, format_dict(result, width=24)

    @argument_command('archive_peek', spec=ARCHIVE_PEEK_SPEC)
    def archive_peek(self, args_dict):
        limit = args_dict['limit']
        if limit < 1:
            return 0, 'Option "--limit" must be greater than zero'
        try:
            path = self.path_resolver.require_existing_file(args_dict['path'])
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    rows = [(item.filename, get_size(item.file_size),
                             '%04d-%02d-%02d' % item.date_time[:3])
                            for item in archive.infolist()[:limit + 1]]
            elif tarfile.is_tarfile(path):
                with tarfile.open(path, 'r:*') as archive:
                    rows = [(item.name, get_size(item.size),
                             time.strftime('%Y-%m-%d', time.localtime(item.mtime)))
                            for item in islice(archive, limit + 1)]
            else:
                return 0, 'Unsupported archive format (expected ZIP or TAR)'
            if not rows:
                return 1, 'Archive is empty'
            result = format_table(['Name', 'Size', 'Date'], rows[:limit])
            if len(rows) > limit:
                result += f'\n... and more (limited to {limit})'
            return 1, result
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
            return 0, f'Failed to peek archive: {exc}'
