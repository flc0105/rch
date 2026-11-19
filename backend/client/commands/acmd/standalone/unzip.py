"""Extract a ZIP safely through the shared Remote Files archive service."""

import time

from client.commands.acmd.decorators import argument_command
from client.commands.runtime.interrupts import cancel_policy
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.formatting import format_bytes
from client.runtime.filesystem.conflict_policy import POLICIES


UNZIP_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='unzip',
    description='Safely extract a ZIP archive',
    options=[
        ArgumentOptionSpec(name='path', required=True, allow_empty=False,
                           positional_index=0, help_text='ZIP archive to extract'),
        ArgumentOptionSpec(name='dest', default='.', alias='d',
                           help_text='Existing output directory (default: current directory)'),
        ArgumentOptionSpec(name='conflict', default='stop',
                           help_text='If target exists: stop, skip, keep_both, merge or replace'),
        ArgumentOptionSpec(name='merge', option_type='flag', default=False,
                           help_text='Shortcut for --conflict merge'),
        ArgumentOptionSpec(name='skip', option_type='flag', default=False,
                           help_text='Shortcut for --conflict skip'),
        ArgumentOptionSpec(name='verbose', option_type='flag', alias='v', default=False,
                           help_text='Show every extracted filename'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False, alias='h',
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd unzip myfolder.zip',
        'acmd unzip myfolder.zip --dest ./restore',
        'acmd unzip myfolder.zip --conflict keep_both',
        'acmd unzip --path myfolder.zip -d ./restore --merge',
        'acmd unzip myfolder.zip --skip',
    ],
)


@argument_command('unzip', spec=UNZIP_ARGUMENT_SPEC)
@cancel_policy('cooperative')
def unzip(self, args_dict, payload=None):
    shortcuts = [name for name in ('merge', 'skip') if args_dict.get(name)]
    explicit_conflict = 'conflict' in (payload or {}).get('args', {})
    if len(shortcuts) > 1 or (shortcuts and explicit_conflict):
        raise ValueError('Choose one conflict strategy: --merge, --skip or --conflict <policy>')
    policy = shortcuts[0] if shortcuts else str(args_dict.get('conflict') or 'stop').strip().lower()
    if policy not in POLICIES:
        raise ValueError('Invalid --conflict policy: {} (use stop, skip, keep_both, merge or replace)'.format(policy))

    archive_path = self.path_resolver.require_existing_file(args_dict['path'])
    destination = self.path_resolver.require_existing_directory(args_dict.get('dest') or '.')
    verbose = bool(args_dict.get('verbose'))
    started = time.monotonic()
    files = byte_count = 0
    if verbose:
        self.emit_progress(f'UNZIP: {archive_path} -> {destination}')

    def on_event(kind, path, value=0):
        nonlocal files, byte_count
        files += 1
        byte_count += int(value)
        if verbose:
            self.emit_progress(f'UNZIP file: {path}')

    result = self.archive_service.extract_zip_with_policy(
        archive_path, destination, policy=policy, on_event=on_event,
    )
    if result.get('skipped'):
        return 1, f'[!] UNZIP skipped: target already exists\n{result["extracted_to"]}'
    return (1,
            f'[+] UNZIP complete: {files} files, {format_bytes(byte_count)}, '
            f'{time.monotonic() - started:.1f}s\n{result["extracted_to"]}')
