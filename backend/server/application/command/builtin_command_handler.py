from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from core.protocol.result_envelope import ResultEnvelope
from core.protocol.message_queue import ResultChunk
from core.utils.command_output import OutputFormat, render_result_payload
from core.utils.command_help import render_grouped_client_help
from server.application.command.builtin_command_support import (
    AliasBuiltinSupport,
    HistoryBuiltinSupport,
    PinnedPathBuiltinSupport,
    RttBuiltinSupport,
    ScriptBuiltinSupport,
    UploadBuiltinSupport,
)
from server.application.command.external_tool_cli_builtin_support import ExternalToolCliBuiltinSupport
from server.application.command.command_output_builtin_support import CommandOutputBuiltinSupport
from server.application.command.command_notify_builtin_support import CommandNotifyBuiltinSupport
from server.application.command.control_builtin_support import ControlBuiltinSupport
from server.application.command.job_builtin_support import JobBuiltinSupport


from server.application.command.configuration_builtin_support import ConfigurationBuiltinSupport


class BuiltinCommandHandler:
    """
    内建命令处理器。

    职责：
    - 提供内建命令候选项
    - 仅分发显式注册的 upload / script / alias / history / job 等内建命令
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
        builtin_services,
        use_foreground_guard=False,
    ):
        self.conn = conn
        self.server = server
        self.plan_builder = plan_builder
        self.remote_execution_service = remote_execution_service
        self.history_entry_id_provider = history_entry_id_provider
        self.plan_executor_factory = plan_executor_factory
        self.command_processor_factory = command_processor_factory
        self.services = builtin_services

        self.configuration_support = ConfigurationBuiltinSupport(
            conn, remote_execution_service, history_entry_id_provider, use_foreground_guard)
        self.upload_support = UploadBuiltinSupport(
            conn=self.conn,
            remote_execution_service=self.remote_execution_service,
            history_entry_id_provider=self.history_entry_id_provider,
        )
        self.job_support = JobBuiltinSupport(
            server=self.server, conn=self.conn,
            remote_execution_service=self.remote_execution_service,
            background_job_service=self.services.background_job_service,
            job_catalog_service=self.services.job_catalog_service,
            history_entry_id_provider=self.history_entry_id_provider,
        )
        self.script_support = ScriptBuiltinSupport(
            plan_builder=self.plan_builder,
            plan_executor_factory=self.plan_executor_factory,
            conn=self.conn,
            remote_execution_service=self.remote_execution_service,
            use_foreground_guard=use_foreground_guard,
        )
        self.command_output_support = CommandOutputBuiltinSupport(
            server=self.server,
            conn=self.conn,
            plan_builder=self.plan_builder,
            plan_executor_factory=self.plan_executor_factory,
            history_entry_id_provider=self.history_entry_id_provider,
            artifact_service=self.services.artifact_service,
            event_bus=self.services.event_bus,
        )
        self.command_notify_support = CommandNotifyBuiltinSupport(
            conn=self.conn,
            plan_builder=self.plan_builder,
            history_entry_id_provider=self.history_entry_id_provider,
            device_event_service=self.services.device_event_service,
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
            pinned_path_store=self.services.pinned_path_store,
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
            history_entry_id_provider=self.history_entry_id_provider,
            catalog_service=self.services.external_tool_catalog_service,
            runtime_service=self.services.external_tool_runtime_service,
            param_preset_store=self.services.external_tool_param_preset_store,
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
                'help': f'Alias [{alias_platform}] -> {alias_command}',
                'source': 'alias'
            })

        return candidates

    def resolve_builtin_command(self, name, arg):
        if self.REGISTRY.get(name) is None:
            return None
        try:
            spec, subcommand, remaining = self.REGISTRY.parse(name, arg)
            if spec.structured:
                # Only the Server registry parses structured builtin arguments.
                # All other builtins retain their original raw-tail contracts.
                platform = getattr(getattr(self.conn, 'session_info', None), 'os_alias', '')
                invocation = self.REGISTRY.parse_leaf(
                    spec, subcommand, remaining,
                    literal_backslashes=platform in ('windows', 'win'))
                return getattr(self, spec.handler)(invocation)
        except ValueError as exc:
            format = getattr(exc, 'output_format', OutputFormat.TEXT)
            return iter(((0, render_result_payload(ResultEnvelope(
                status='error', message=str(exc)).as_payload(), format)),))
        handler = getattr(self, spec.handler)
        if spec.dispatch_subcommand:
            return handler(subcommand, remaining)
        if subcommand is not None:
            return handler(subcommand + ((' ' + remaining) if remaining else ''))
        return handler(remaining)

    def server_help(self, invocation):
        target = str(invocation.arguments.get('target') or '').strip()
        subcommand = str(invocation.arguments.get('subcommand') or '').strip()
        try:
            if target in ('', 'server'):
                if subcommand:
                    raise ValueError('help target takes no subcommand')
                lines = ['Server Commands:', self.REGISTRY.help()]
                if target == '':
                    lines.extend(['', 'Client Commands:', self._client_help()])
                result = '\n'.join(lines)
            elif target == 'client':
                if subcommand:
                    raise ValueError('help client takes no subcommand')
                result = self._client_help()
            else:
                result = self.REGISTRY.help(' '.join(part for part in (target, subcommand) if part))
            status = 1
        except ValueError as exc:
            status, result = 0, str(exc)
        envelope = ResultEnvelope(status='success' if status == 1 else 'error', message=result).as_payload()
        yield ResultChunk(status, render_result_payload(envelope, invocation.output_format), True,
                          terminal_authoritative=True, event=envelope)

    def _client_help(self):
        """Recreate the Client's native help groups from the handshake manifest."""
        manifest = getattr(getattr(self.conn, 'session_info', None), 'command_manifest', None) or []
        grouped = {}
        for item in manifest:
            if not isinstance(item, dict) or item.get('suggest', True) is False:
                continue
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            group = str(item.get('group') or 'general')
            # Client help shows actual ACMD names, not autocomplete-only help templates.
            if group == 'acmd' and (name == 'acmd' or name.startswith('acmd help ')):
                continue
            grouped.setdefault(group, []).append((name, str(item.get('help') or '')))
        return render_grouped_client_help(grouped) or 'No Client commands available'

    def config(self, invocation):
        yield from self.configuration_support.config(invocation)

    def watchdog(self, invocation):
        yield from self.configuration_support.watchdog(invocation)

    def upload(self, invocation):
        try:
            yield from self.upload_support.upload(invocation)
        except (FileNotFoundError, ValueError) as exc:
            yield 0, render_result_payload(ResultEnvelope(
                status='error', message=str(exc)).as_payload(), invocation.output_format)

    def saveout(self, invocation):
        for item in self.command_output_support.saveout(invocation.arguments['command']):
            status, message = item[:2]
            envelope = item.event
            yield ResultChunk(status, render_result_payload(envelope, invocation.output_format), True,
                              terminal_authoritative=True, event=envelope)

    def notify(self, invocation):
        for item in self.command_notify_support.notify(invocation.arguments['command']):
            yield item

    def xt(self, arg=''):
        for item in self.external_tool_cli_support.xt(arg):
            yield item


    def script(self, invocation):
        yield from self.script_support.script(invocation)

    def alias(self, subcommand, remaining=''):
        yield from self.alias_support.execute_subcommand(subcommand, remaining)


    def job(self, invocation):
        yield from self.job_support.execute_subcommand(invocation)

    def history(self, invocation):
        for item in self.history_support.history(invocation):
            yield item

    def gopin(self, invocation):
        yield from self.pinned_path_support.gopin(invocation)

    def rtt(self, invocation):
        for item in self.rtt_support.rtt(invocation):
            yield item

    def httpctl(self, invocation):
        yield from self.control_support.httpctl(invocation)
