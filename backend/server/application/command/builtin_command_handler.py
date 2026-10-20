from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
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
from server.application.command.interaction_builtin_support import BuiltinInteractionSupport
from server.application.command.job_builtin_support import JobBuiltinSupport
from server.application.command.advanced_builtin_support import AdvancedBuiltinSupport


class BuiltinCommandHandler:
    """
    内建命令处理器。

    职责：
    - 提供内建命令候选项
    - 分发 upload / exec / alias / unalias / history / rtt 等内建命令
    - 不负责命令总路由，也不直接决定 alias / default / acmd 的分流
    """

    REGISTRY = SERVER_COMMAND_REGISTRY

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
        self.job_support = JobBuiltinSupport(
            server=self.server, conn=self.conn,
            remote_execution_service=self.remote_execution_service,
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
        self.interactions = BuiltinInteractionSupport(server=self.server, conn=self.conn)
        self.advanced_builtins = AdvancedBuiltinSupport(self.conn, self.interactions)

        self.external_tool_cli_support = ExternalToolCliBuiltinSupport(
            server=self.server,
            conn=self.conn,
            command_processor_factory=self.command_processor_factory,
        )

    def get_command_candidates(self):
        candidates = self.REGISTRY.candidates()

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
        if self.REGISTRY.get(name) is None:
            return None
        try:
            spec, subcommand, remaining = self.REGISTRY.parse(name, arg)
        except ValueError as exc:
            return iter(((0, str(exc)),))
        handler = getattr(self, spec.handler)
        if subcommand is None:
            return handler(remaining)
        if name == 'script':
            return self.script_support.script(subcommand, remaining)
        if name == 'alias':
            return self.alias_support.execute_subcommand(subcommand, remaining)
        if name == 'job':
            return self.job_support.execute_subcommand(subcommand, remaining)
        # XT, History and HTTP control keep their existing business-specific
        # argument semantics; only command/subcommand recognition is centralized.
        if name == 'history' and subcommand == 'list':
            return handler('')
        if name == 'xt' and subcommand == '__direct__':
            return handler(remaining)
        if name == 'httpctl' and subcommand == 'help':
            return handler('help')
        return handler(subcommand + ((' ' + remaining) if remaining else ''))

    def server_help(self, target=''):
        target = str(target or '').strip()
        if target in ('', 'server'):
            lines = ['Server Commands:', self.REGISTRY.help()]
            if target == '':
                lines.extend(['', 'Client Commands:', self._client_help(),
                              '', 'Aliases:', self._alias_help()])
            yield 1, '\n'.join(lines)
            return
        if target == 'client':
            yield 1, self._client_help()
            return
        if target == 'alias':
            yield 1, self._alias_help()
            return
        try:
            yield 1, self.REGISTRY.help(target)
        except ValueError as exc:
            yield 0, str(exc)

    def _client_help(self):
        manifest = getattr(getattr(self.conn, 'session_info', None), 'command_manifest', None) or []
        lines = [f"{str(item.get('name') or ''):<22} {str(item.get('help') or '')}"
                 for item in manifest if isinstance(item, dict)
                 and item.get('name') and item.get('suggest', True) is not False]
        return '\n'.join(sorted(lines, key=str.lower)) or 'No Client commands available'

    def _alias_help(self):
        rows = self.alias_support.list_resolved_aliases()
        return '\n'.join(f"{row['alias']} -> {row['command']}" for row in rows) or 'No aliases available'

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


    def script(self, arg=''):
        # Subcommand resolution is managed by the shared registry.
        yield from self.script_support.script(*self.REGISTRY.parse('script', arg)[1:])

    def alias(self, arg=''):
        for item in self.alias_support.alias(arg):
            yield item


    def job(self, arg=''):
        yield from self.job_support.job(arg)

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

    def disconnect(self, arg=''):
        yield from self.advanced_builtins.disconnect(arg)

