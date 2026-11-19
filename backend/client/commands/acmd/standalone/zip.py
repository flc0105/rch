"""ACMD ZIP: strict by default, with optional progress and explicit partial archives."""

import os
import time

from client.commands.acmd.decorators import argument_command
from client.commands.runtime.interrupts import cancel_policy
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.formatting import format_bytes


ZIP_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='zip',
    description='Create a ZIP archive from a file or directory',
    options=[
        ArgumentOptionSpec(name='path', required=True, allow_empty=False,
                           positional_index=0, help_text='File or directory to archive'),
        ArgumentOptionSpec(name='dest', default='', alias='d',
                           help_text='Existing output directory (default: source parent)'),
        ArgumentOptionSpec(name='name', default='', alias='n',
                           help_text='Output ZIP filename (default: <source>.zip)'),
        ArgumentOptionSpec(name='skip-unreadable', option_type='flag', default=False,
                           help_text='Explicitly omit unreadable files/directories (partial ZIP)'),
        ArgumentOptionSpec(name='verbose', option_type='flag', alias='v', default=False,
                           help_text='Show every archived filename'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False, alias='h',
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd zip myfolder',
        'acmd zip report.txt',
        'acmd zip .',
        'acmd zip myfolder --dest ./backups --name snapshot.zip',
        'acmd zip --path myfolder --name snapshot.zip -d ./backups',
        'acmd zip . --skip-unreadable -v',
    ],
)


@argument_command('zip', spec=ZIP_ARGUMENT_SPEC)
@cancel_policy('cooperative')
def zip(self, args_dict, payload=None):
    source = self.path_resolver.require_existing_non_empty_path(args_dict['path'])
    destination = self.path_resolver.require_existing_directory(
        args_dict.get('dest') or os.path.dirname(source)
    )
    name = str(args_dict.get('name') or '').strip()
    # --name is strictly a filename; --dest owns the output directory.
    if name and (os.path.basename(name) != name or name in ('.', '..')):
        raise ValueError('--name must be a filename; use --dest for the output directory')

    verbose = bool(args_dict.get('verbose'))
    started = time.monotonic()
    files = byte_count = skipped_count = 0
    if verbose:
        self.emit_progress(f'ZIP: {source} -> {destination}')

    def on_event(kind, path, value=0):
        nonlocal files, byte_count, skipped_count
        if kind == 'skipped':
            skipped_count += 1
            self.emit_progress(f'Skipped unreadable: {path} ({value})', level='warning')
        else:
            files += 1
            byte_count += int(value)
            if verbose:
                self.emit_progress(f'ZIP file: {path}')

    archive_path = self.archive_service.create_zip_in_directory(
        [source], destination, archive_name=name,
        on_event=on_event, skip_unreadable=bool(args_dict.get('skip-unreadable')),
    )
    if skipped_count and not files:
        # A zero-file archive with skipped sources is not a valid backup.
        os.remove(archive_path)
        raise ValueError('ZIP contains no readable files; all inputs were skipped')
    outcome = 'partial' if skipped_count else 'complete'
    skipped = f' (skipped {skipped_count} unreadable)' if skipped_count else ''
    return (1,
            f'[+] ZIP {outcome}: {files} files, {format_bytes(byte_count)}, '
            f'{time.monotonic() - started:.1f}s{skipped}\n{archive_path}')
