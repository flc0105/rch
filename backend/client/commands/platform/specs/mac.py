from client.commands.arguments.models import ArgumentCommandSpec, ArgumentOptionSpec

MSGBOX_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='msgbox',
    description='Show a native macOS dialog',
    options=[
        ArgumentOptionSpec(name='title', option_type='str', required=False, default='', allow_empty=True,
                           help_text='Dialog title'),
        ArgumentOptionSpec(name='text', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Dialog text'),
        ArgumentOptionSpec(name='timeout', option_type='int', required=False, default=None,
                           help_text='Auto close timeout in seconds'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

NOTIFY_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='notify',
    description='Show a native macOS notification',
    options=[
        ArgumentOptionSpec(name='title', option_type='str', required=False, default='', allow_empty=True,
                           help_text='Notification title'),
        ArgumentOptionSpec(name='text', option_type='str', required=True, default=None, allow_empty=False,
                           help_text='Notification text'),
        ArgumentOptionSpec(name='sound', option_type='flag', required=False, default=False,
                           help_text='Play the default notification sound'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

SQLITE_QUERY_SPEC = ArgumentCommandSpec(
    name='sqlite_query',
    description='Read-only SQLite query',
    options=[
        ArgumentOptionSpec(name='db', option_type='str', required=True, help_text='Database file path'),
        ArgumentOptionSpec(name='query', option_type='str', required=True, help_text='SQL query'),
        ArgumentOptionSpec(name='json', option_type='flag', required=False, default=False,
                           help_text='Output as JSON'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd sqlite_query --db /Users/flc/studio.db --query "PRAGMA table_list;"',
        'acmd sqlite_query --db /Users/flc/studio.db --query "PRAGMA table_info(\'bookings\')"',
        'acmd sqlite_query --db /Users/flc/studio.db --query "select * from scenes"'
    ]
)

IMAGE_INFO_SPEC = ArgumentCommandSpec(
    name='image_info',
    description='Show image metadata',
    options=[
        ArgumentOptionSpec(name='path', option_type='str', required=True, help_text='Image file path',
                           positional_index=0),
        ArgumentOptionSpec(name='json', option_type='flag', required=False, default=False,
                           help_text='Output as JSON'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

IMPORT_CHECK_SPEC = ArgumentCommandSpec(
    name='import_check',
    description='Check Python package/module status',
    options=[
        ArgumentOptionSpec(name='module', option_type='str', required=True, help_text='Module name',
                           positional_index=0),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)

ARCHIVE_PEEK_SPEC = ArgumentCommandSpec(
    name='archive_peek',
    description='List archive contents without extracting',
    options=[
        ArgumentOptionSpec(name='path', option_type='str', required=True, help_text='Archive file path'),
        ArgumentOptionSpec(name='limit', option_type='int', required=False, default=50,
                           help_text='Limit number of entries'),
        ArgumentOptionSpec(name='help', option_type='flag', required=False, default=False,
                           help_text='Show this help message'),
    ]
)


LAUNCHD_ARGUMENT_SPEC = ArgumentCommandSpec(
    name='launchd',
    description='Manage a macOS LaunchAgent or LaunchDaemon',
    options=[
        # Required execution choices are collected through Interaction Broker if omitted.
        ArgumentOptionSpec(name='action', option_type='str', required=True, default='', allow_empty=False,
                           positional_index=0, help_text='install, start, stop, restart, uninstall, status'),
        ArgumentOptionSpec(name='kind', option_type='str', required=True, default='', allow_empty=False,
                           positional_index=1, help_text='agent or daemon'),
        ArgumentOptionSpec(name='label', option_type='str', default='com.rch.client', allow_empty=False,
                           help_text='launchd service label'),
        ArgumentOptionSpec(name='keep_alive', option_type='bool', default=True,
                           help_text='Set KeepAlive when installing'),
        ArgumentOptionSpec(name='run_at_load', option_type='bool', default=True,
                           help_text='Set RunAtLoad when installing'),
        ArgumentOptionSpec(name='scope', option_type='str', default='user', allow_empty=False,
                           help_text='LaunchAgent scope: user or global'),
        ArgumentOptionSpec(name='target_user', option_type='str', default='', allow_empty=True,
                           help_text='LaunchAgent target username or UID; blank selects current GUI user'),
        ArgumentOptionSpec(name='no-confirm', option_type='flag', default=False,
                           help_text='Execute directly; requires action and kind'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False,
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd launchd install agent --scope user --keep-alive true',
        'acmd launchd --action start --kind agent',
        'acmd launchd status daemon',
        'acmd launchd uninstall agent --label com.rch.client',
    ],
)
