from core.commands.argument_models import ArgumentOptionSpec, ArgumentCommandSpec

ALERT_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='alert',
    description='Show alert dialog',
    options=[
        ArgumentOptionSpec(name='title', option_type='str', required=False, default='Alert', allow_empty=True,
                           help_text='Dialog title'),
        ArgumentOptionSpec(name='message', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Dialog text'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

NOTIFY_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='notify',
    description='Send local notification',
    options=[
        ArgumentOptionSpec(name='title', option_type='str', required=False, default='Notice', allow_empty=True,
                           help_text='Notification title'),
        ArgumentOptionSpec(name='message', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Notification text'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

FIND_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='find',
    description='Find files by keyword',
    options=[
        ArgumentOptionSpec(name='path', option_type='str', required=False, default='.', allow_empty=True,
                           help_text='Target directory', positional_index=0),
        ArgumentOptionSpec(name='keyword', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Keyword to search in file or directory names'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

TREE_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='tree',
    description='Show directory tree',
    options=[
        ArgumentOptionSpec(name='path', option_type='str', required=False, default='.', allow_empty=True,
                           help_text='Target directory', positional_index=0),
        ArgumentOptionSpec(name='max_depth', option_type='int', required=False, default=3, alias="L",
                           help_text='Maximum recursion depth'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

HEAD_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='head',
    description='Show first N lines of a text file',
    options=[
        ArgumentOptionSpec(name='path', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Text file path', positional_index=0),
        ArgumentOptionSpec(name='lines', option_type='int', required=False, default=10, alias='n',
                           help_text='Number of lines to show'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

TAIL_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='tail',
    description='Show last N lines of a text file',
    options=[
        ArgumentOptionSpec(name='path', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Text file path', positional_index=0),
        ArgumentOptionSpec(name='lines', option_type='int', required=False, default=10, alias='n',
                           help_text='Number of lines to show'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

WGET_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='wget',
    description='Download file from URL',
    options=[
        ArgumentOptionSpec(name='url', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Source URL', positional_index=0),
        ArgumentOptionSpec(name='output', option_type='str', required=False, default='', alias='o',
                           help_text='Output file path'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)
