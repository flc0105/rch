"""List the mounted volumes shown by the desktop Dashboard."""

from client.commands.acmd.decorators import argument_command
from client.runtime.filesystem.storage_volumes import collect_storage_volumes
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, ResultDataShape, resolve_presentation, render_structured_result
from core.utils.formatting import format_bytes


DRIVES_SPEC = ArgumentCommandSpec(
    name='drives',
    description='List mounted drives',
    options=[
        ArgumentOptionSpec('format', 'str', default='', alias='f',
                           choices=('table', 'records', 'json'), help_text='Supported output: table, records, json'),
        ArgumentOptionSpec('json', 'flag', default=False, help_text='Output as JSON'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=['acmd drives', 'acmd drives --json'],
)


@argument_command('drives', spec=DRIVES_SPEC, platforms=('mac', 'win', 'linux'))
def drives(self, args_dict):
    try:
        import psutil
    except ImportError:
        return 0, 'psutil is unavailable in this Client Python runtime'

    volumes = collect_storage_volumes(psutil, self.command_platform)
    rows = [
        {
            'mountpoint': volume['mountpoint'],
            'name': volume['name'],
            'fstype': volume['fstype'],
            'total': format_bytes(volume['total']),
            'used': format_bytes(volume['used']),
            'system': volume['system'],
            'kind': volume['kind'],
        }
        for volume in volumes
    ]
    output, layout = resolve_presentation(args_dict, ResultDataShape.TABLE)
    result = StructuredCommandResult(status=1, data=rows, shape=layout)
    return render_structured_result(result, output_format=output)
