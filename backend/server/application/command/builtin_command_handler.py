from server.application.command.builtin_command_support import (
    AliasBuiltinSupport,
    HistoryBuiltinSupport,
    PinnedPathBuiltinSupport,
    RttBuiltinSupport,
    ScriptBuiltinSupport,
    UploadBuiltinSupport, ExternalToolCliBuiltinSupport,
)
from server.application.command.command_output_builtin_support import CommandOutputBuiltinSupport
from server.application.command.command_notify_builtin_support import CommandNotifyBuiltinSupport
from server.application.command.control_builtin_support import ControlBuiltinSupport


class BuiltinCommandHandler:
    """
    内建命令处理器。

    职责：
    - 提供内建命令候选项
    - 分发 upload / exec / alias / unalias / history / rtt 等内建命令
    - 不负责命令总路由，也不直接决定 alias / default / acmd 的分流
    """

    WEB_COMMAND_TEMPLATES = [
        {
            'name': 'upload',
            'template': 'upload ',
            'help': 'upload <local_file> | Upload a local file to the client',
            'source': 'server'
        },
        {
            'name': 'exec',
            'template': 'exec ',
            'help': 'exec <script.py> | Execute a server-side Python script on the client',
            'source': 'server'
        },
        {
            'name': 'run_script',
            'template': 'run_script ',
            'help': 'run_script <payload> | Execute a structured server-side script on the client',
            'source': 'server'
        },
        {
            'name': 'alias',
            'template': 'alias ',
            'help': 'alias set|unset|list|resolve|reload [--platform supported-platform]',
            'source': 'server'
        },
        {
            'name': 'history',
            'template': 'history',
            'help': 'Show de-duplicated command history for the current host. Use history run <index> or !<index> to run an item quickly',
            'source': 'server'
        },
        {
            'name': 'gopin',
            'template': 'gopin ',
            'help': 'gopin <display_name> | Jump to a saved quick jump path for the current host',
            'source': 'server'
        },
        {
            'name': 'rtt',
            'template': 'rtt',
            'help': 'Show current heartbeat RTT / last seen state',
            'source': 'server'
        },
        {
            'name': 'httpctl',
            'template': 'httpctl ',
            'help': 'httpctl kill|relaunch|clone | Client HTTP control channel',
            'source': 'server'
        },

        {
            'name': 'saveout',
            'template': 'saveout ',
            'help': 'saveout <client-command> | Save full client command output as artifact',
            'source': 'server'
        },
        {
            'name': 'notify',
            'template': 'notify ',
            'help': 'notify <client-command> | Run a client command and notify when it finishes',
            'source': 'server'
        },
        {
            'name': 'xt',
            'template': 'xt ',
            'help': 'xt list|info|which|<alias> [--] <raw args> | External tool CLI facade',
            'source': 'server'
        },
    ]

    def __init__(
        self,
        conn,
        server,
        plan_builder,
        remote_execution_service,
        history_entry_id_provider,
        plan_executor_factory,
        command_processor_factory,
    ):
        self.conn = conn
        self.server = server
        self.plan_builder = plan_builder
        self.remote_execution_service = remote_execution_service
        self.history_entry_id_provider = history_entry_id_provider
        self.plan_executor_factory = plan_executor_factory
        self.command_processor_factory = command_processor_factory

        self.upload_support = UploadBuiltinSupport(
            conn=self.conn,
            remote_execution_service=self.remote_execution_service,
            history_entry_id_provider=self.history_entry_id_provider,
        )
        self.script_support = ScriptBuiltinSupport(
            plan_builder=self.plan_builder,
            plan_executor_factory=self.plan_executor_factory,
        )
        self.command_output_support = CommandOutputBuiltinSupport(
            server=self.server,
            conn=self.conn,
            plan_builder=self.plan_builder,
            plan_executor_factory=self.plan_executor_factory,
            history_entry_id_provider=self.history_entry_id_provider,
        )
        self.command_notify_support = CommandNotifyBuiltinSupport(
            server=self.server,
            conn=self.conn,
            plan_builder=self.plan_builder,
            history_entry_id_provider=self.history_entry_id_provider,
        )

        self.alias_support = AliasBuiltinSupport(
            alias_manager=self.server.alias_manager,
            conn=self.conn,
        )
        self.history_support = HistoryBuiltinSupport(
            command_history=self.server.command_history,
            conn=self.conn,
            history_entry_id_provider=self.history_entry_id_provider,
            command_processor_factory=self.command_processor_factory,
        )
        self.pinned_path_support = PinnedPathBuiltinSupport(
            pinned_path_store=self.server.web_service.pinned_path_api.pinned_path_store,
            command_history=self.server.command_history,
            conn=self.conn,
            history_entry_id_provider=self.history_entry_id_provider,
            command_processor_factory=self.command_processor_factory,
        )
        self.rtt_support = RttBuiltinSupport(
            conn=self.conn,
        )
        self.control_support = ControlBuiltinSupport(
            conn=self.conn,
        )

        self.external_tool_cli_support = ExternalToolCliBuiltinSupport(
            server=self.server,
            conn=self.conn,
            command_processor_factory=self.command_processor_factory,
        )

    def get_command_candidates(self):
        candidates = [dict(item) for item in self.WEB_COMMAND_TEMPLATES]

        for item in self.alias_support.list_resolved_aliases():
            alias_name = item.get('alias') or ''
            alias_command = item.get('command') or ''
            alias_platform = item.get('platform') or 'common'

            if not alias_name:
                continue

            candidates.append({
                'name': alias_name,
                'template': alias_name,
                'help': f'Alias [{alias_platform}] -> {alias_command}',
                'source': 'alias'
            })

        return candidates

    def resolve_builtin_command(self, name, arg):
        if not hasattr(self, name):
            return None

        handler = getattr(self, name)
        if not callable(handler):
            return None

        return handler(arg)

    def upload(self, filename):
        for item in self.upload_support.upload(filename):
            yield item

    def saveout(self, command):
        for item in self.command_output_support.saveout(command):
            yield item

    def notify(self, command):
        for item in self.command_notify_support.notify(command):
            yield item

    def xt(self, arg=''):
        for item in self.external_tool_cli_support.xt(arg):
            yield item


    def exec(self, filename):
        if not filename:
            yield 1, '\n'.join(self.script_support.list_scripts())
            return

        for item in self.script_support.execute_script_file(filename):
            yield item

    def run_script(self, payload_text):
        if not payload_text:
            yield 0, 'Usage: run_script <payload>'
            return

        for item in self.script_support.execute_script_payload(payload_text):
            yield item

    def alias(self, arg=''):
        for item in self.alias_support.alias(arg):
            yield item


    def history(self, arg):
        for item in self.history_support.history(arg):
            yield item

    def gopin(self, arg=''):
        for item in self.pinned_path_support.gopin(arg):
            yield item

    def rtt(self, arg=''):
        for item in self.rtt_support.rtt(arg):
            yield item

    def httpctl(self, arg=''):
        for item in self.control_support.httpctl(arg):
            yield item
