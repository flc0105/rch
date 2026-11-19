"""Create a ZIP alongside its source, using the shared Remote Files archive service."""

import os

from client.commands.acmd.decorators import argument_command
from client.commands.runtime.interrupts import cancel_policy
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, render_structured_result


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
        ArgumentOptionSpec(name='json', option_type='flag', default=False,
                           help_text='Output result as JSON'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False, alias='h',
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd zip myfolder',
        'acmd zip report.txt',
        'acmd zip .',
        'acmd zip myfolder --dest ./backups --name snapshot.zip',
        'acmd zip myfolder --json',
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

    archive_path = self.archive_service.create_zip_in_directory(
        [source], destination, archive_name=name,
    )
    return render_structured_result(
        StructuredCommandResult(status=1, data={'archive_path': archive_path}, shape='dict', width=14),
        output_format='json' if args_dict.get('json') else 'text',
    )
