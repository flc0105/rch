"""Extract a ZIP safely through the shared Remote Files archive service."""

from client.commands.acmd.decorators import argument_command
from client.commands.runtime.interrupts import cancel_policy
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, render_structured_result
from client.runtime.filesystem.conflict_policy import POLICIES


UNZIP_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='unzip',
    description='Safely extract a ZIP archive',
    options=[
        ArgumentOptionSpec(name='archive', required=True, allow_empty=False,
                           positional_index=0, help_text='ZIP archive to extract'),
        ArgumentOptionSpec(name='dest', default='.', alias='d',
                           help_text='Existing output directory (default: current directory)'),
        ArgumentOptionSpec(name='conflict', default='stop',
                           help_text='If target exists: stop, skip, keep_both, merge or replace'),
        ArgumentOptionSpec(name='json', option_type='flag', default=False,
                           help_text='Output result as JSON'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False, alias='h',
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd unzip myfolder.zip',
        'acmd unzip myfolder.zip --dest ./restore',
        'acmd unzip myfolder.zip --conflict keep_both',
        'acmd unzip myfolder.zip --json',
    ],
)


@argument_command('unzip', spec=UNZIP_ARGUMENT_SPEC)
@cancel_policy('cooperative')
def unzip(self, args_dict, payload=None):
    policy = str(args_dict.get('conflict') or 'stop').strip().lower()
    if policy not in POLICIES:
        raise ValueError('Invalid --conflict policy: {} (use stop, skip, keep_both, merge or replace)'.format(policy))

    archive_path = self.path_resolver.require_existing_file(args_dict['archive'])
    destination = self.path_resolver.require_existing_directory(args_dict.get('dest') or '.')
    result = self.archive_service.extract_zip_with_policy(
        archive_path, destination, policy=policy,
    )
    data = {
        'extracted_to': result['extracted_to'],
        'file_count': result['file_count'],
        'dir_count': result['dir_count'],
        'skipped': bool(result.get('skipped')),
    }
    return render_structured_result(
        StructuredCommandResult(status=1, data=data, shape='dict', width=14),
        output_format='json' if args_dict.get('json') else 'text',
    )
