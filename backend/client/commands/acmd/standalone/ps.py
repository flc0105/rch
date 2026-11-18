"""ACMD ps: list and filter Client processes, reusing ProcessService."""

from client.runtime.execution.process.process_service import ProcessService
from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, render_structured_result


PS_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='ps',
    description='Show running processes',
    options=[
        ArgumentOptionSpec(
            name='pid',
            option_type='int',
            required=False,
            default=None,
            alias='p',
            positional_index=0,
            help_text='Filter by process id',
        ),
        ArgumentOptionSpec(
            name='name',
            option_type='str',
            required=False,
            default='',
            alias='n',
            help_text='Filter by process name or executable path',
        ),
        ArgumentOptionSpec(
            name='port', option_type='int', required=False, default=None,
            help_text='Filter by listening port',
        ),
        ArgumentOptionSpec(
            name='with-actions', option_type='flag', required=False, default=False,
            help_text='Include available row actions in JSON output',
        ),
        ArgumentOptionSpec(
            name='json',
            option_type='flag',
            required=False,
            default=False,
            help_text='Output as JSON',
        ),
        ArgumentOptionSpec(
            name='help',
            option_type='flag',
            required=False,
            default=False,
            alias='h',
            help_text='Show this help message',
        ),
    ],
    examples=[
        'acmd ps',
        'acmd ps 1234',
        'acmd ps --pid 1234',
        'acmd ps --name python',
        'acmd ps --name python --json',
        'acmd ps --port 8080 --json --with-actions',
    ],
)

def process_int(value):
    """Match the previous ps display normalization for missing process IDs."""
    if value in (None, ''):
        return 0
    try:
        return int(value)
    except Exception:
        return 0


@argument_command('ps', spec=PS_ARGUMENT_SPEC, platforms=('mac', 'win', 'linux'))
def ps(self, args_dict, payload=None):
    """List Client processes and apply ACMD filters before rendering."""
    pid = args_dict.get('pid')
    name = str(args_dict.get('name') or '').strip()
    output_json = bool(args_dict.get('json', False))
    include_actions = bool(args_dict.get('with-actions', False))
    port = args_dict.get('port')
    if port is not None:
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError('Port must be 1..65535')

    if pid is not None:
        pid = int(pid)
        if pid < 0:
            raise ValueError('PID must not be negative: {}'.format(pid))

    rows = ProcessService(self).list_processes()
    name_lower = name.lower()
    filtered = []
    for row in rows or []:
        row_pid = process_int(row.get('pid'))
        row_name = str(row.get('name') or '')
        if pid is not None and row_pid != pid:
            continue
        if name_lower and name_lower not in row_name.lower():
            continue
        filtered.append({
            'pid': row_pid,
            'ppid': process_int(row.get('ppid')),
            'name': row_name,
            'username': row.get('username') or '',
            'status': row.get('status') or '',
        })
    rows = sorted(filtered, key=lambda item: item['pid'])
    if port is not None:
        from client.runtime.execution.process.approved_process_service import port_owners
        owners = port_owners(port)
        rows = [row for row in rows if row['pid'] in owners]
    if include_actions and output_json:
        for row in rows:
            row['_actions'] = [{'label': 'Kill',
                                'command': f'acmd kill --pid {row["pid"]}'}]

    if not rows:
        if pid is not None and name:
            raise RuntimeError(
                'No process found for pid {} and name {}'.format(pid, name)
            )

        if pid is not None:
            raise RuntimeError(
                'No process found for pid {}'.format(pid)
            )

        if name:
            raise RuntimeError(
                'No process found for name {}'.format(name)
            )
        if port is not None:
            raise RuntimeError('No process found for port {}'.format(port))

        raise RuntimeError('No processes found')

    result = StructuredCommandResult(
        status=1,
        data=rows,
        shape='table',
    )

    return render_structured_result(
        result,
        output_format='json' if output_json else 'text',
    )

