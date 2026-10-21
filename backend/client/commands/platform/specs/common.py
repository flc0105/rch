from client.commands.arguments.models import (
    ArgumentCommandSpec,
    ArgumentOptionSpec,
)


NETSTAT_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='netstat',
    description='Show TCP/UDP network connections',
    options=[
        ArgumentOptionSpec(
            name='port',
            option_type='int',
            required=False,
            default=None,
            alias='p',
            positional_index=0,
            help_text='Filter by local or remote port',
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
        'acmd netstat',
        'acmd netstat 443',
        'acmd netstat --port 443',
        'acmd netstat --port 443 --json',
    ],
)


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

KILL_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='kill', description='Kill processes',
    options=[
        ArgumentOptionSpec(name='pid', option_type='int', default=None, help_text='Process ID'),
        ArgumentOptionSpec(name='name', option_type='str', default='', help_text='Exact process name'),
        ArgumentOptionSpec(name='port', option_type='int', default=None, help_text='Listening port'),
        ArgumentOptionSpec(name='force', option_type='flag', default=False, alias='f', help_text='Use SIGKILL'),
        ArgumentOptionSpec(name='no-confirm', option_type='flag', default=False, help_text='Skip interaction and execute'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False, alias='h', help_text='Show help'),
    ],
    examples=['acmd kill', 'acmd kill --pid 1234', 'acmd kill --name python -9',
              'acmd kill --port 8080 --force', 'acmd kill --pid 1234 --no-confirm'],
)

