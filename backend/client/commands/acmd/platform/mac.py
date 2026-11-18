from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.command_completion.models import CompletionSpec
from client.commands.acmd.decorators import argument_command


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
        ArgumentOptionSpec(name='db', option_type='str', required=True, help_text='Database file path',
                           completion=CompletionSpec('filesystem', ('file', 'directory'))),
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
                           positional_index=0, completion=CompletionSpec('filesystem', ('file', 'directory'))),
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
        ArgumentOptionSpec(name='json', option_type='flag', default=False,
                           help_text='Output the launchd service result as JSON'),
        ArgumentOptionSpec(name='help', option_type='flag', default=False,
                           help_text='Show this help message'),
    ],
    examples=[
        'acmd launchd install agent --scope user --keep-alive true',
        'acmd launchd --action start --kind agent',
        'acmd launchd status daemon',
        'acmd launchd uninstall agent --label com.rch.client',
        'acmd launchd status agent --json',
    ],
)



class MacACMDCommands:

    @argument_command('msgbox', spec=MSGBOX_ARGUMENT_SPEC)
    def _acmd_msgbox(self, args_dict, payload=None):
        return self.mac_automation.acmd_msgbox(args_dict, payload)

    @argument_command('notify', spec=NOTIFY_ARGUMENT_SPEC)
    def _acmd_notify(self, args_dict, payload=None):
        return self.mac_automation.acmd_notify(args_dict, payload)

    @argument_command('sqlite_query', spec=SQLITE_QUERY_SPEC)
    def _acmd_sqlite_query(self, args_dict, payload=None):
        """只读 SQLite 查询"""
        return self.mac_file_inspection.acmd_sqlite_query(args_dict, payload)

    @argument_command('image_info', spec=IMAGE_INFO_SPEC)
    def _acmd_image_info(self, args_dict, payload=None):
        """获取图片信息"""
        return self.mac_file_inspection.acmd_image_info(args_dict, payload)

    @argument_command('import_check', spec=IMPORT_CHECK_SPEC)
    def _acmd_import_check(self, args_dict, payload=None):
        """检查 Python 包是否可以导入"""
        return self.mac_file_inspection.acmd_import_check(args_dict, payload)

    @argument_command('archive_peek', spec=ARCHIVE_PEEK_SPEC)
    def _acmd_archive_peek(self, args_dict, payload=None):
        """查看压缩包内容"""
        return self.mac_file_inspection.acmd_archive_peek(args_dict, payload)

    @argument_command('launchd', spec=LAUNCHD_ARGUMENT_SPEC, interaction=True)
    def _acmd_launchd(self, args_dict, payload=None):
        return self.mac_system.acmd_launchd(args_dict, payload)
