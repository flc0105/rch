from core.command_completion.parser import CommandCompletionParser
from core.command_completion.registry import CommandCompletionRegistry
from server.application.command.server_builtin_registry import SERVER_COMMAND_REGISTRY
from server.application.completion.command_completion_providers import (
    ScriptCommandCompletionProvider,
    JobCommandCompletionProvider,
    ConfigCommandCompletionProvider,
    RegisteredServerSubcommandCompletionProvider,
    HelpCommandCompletionProvider,
    ExternalToolCommandCompletionProvider,
    GopinCommandCompletionProvider,
    HistoryCommandCompletionProvider,

    RemoteClientCommandCompletionProvider,
    ServerFileSystemCompletionProvider,

)


class ServerCommandCompletionService:
    """
    server 侧 command bar 补全服务。
    """

    def __init__(self, server, remote_execution_service, pinned_path_store, job_catalog_service, background_job_service, external_tool_catalog_service, external_tool_client_runtime, script_catalog_service=None):
        self.server = server
        self.parser = CommandCompletionParser()
        self.registry = CommandCompletionRegistry({
            'gopin': GopinCommandCompletionProvider(
                server=server,
                pinned_path_store=pinned_path_store,
            ),
            'history': HistoryCommandCompletionProvider(
                server=server,
                command_history=server.command_history,
            ),
            'subcommands': RegisteredServerSubcommandCompletionProvider(),
            'help': HelpCommandCompletionProvider(),
            'configuration': ConfigCommandCompletionProvider(
                server=server, remote_execution_service=remote_execution_service,
            ),
            'jobs': JobCommandCompletionProvider(
                server=server, job_catalog_service=job_catalog_service,
                background_job_service=background_job_service,
            ),
            'scripts': ScriptCommandCompletionProvider(
                server=server, script_catalog_service=script_catalog_service,
            ),
            'xt': ExternalToolCommandCompletionProvider(
                server=server,
                external_tool_catalog_service=external_tool_catalog_service,
                client_lifecycle_runtime=external_tool_client_runtime,
            ),
            'filesystem': ServerFileSystemCompletionProvider(),
            'client': RemoteClientCommandCompletionProvider(
                server=server, remote_execution_service=remote_execution_service,
            ),
        })

    def complete(self, client_id: str, raw_input: str = '', cursor_position: int | None = None, max_results: int = 50, completion_spec: dict | None = None) -> dict:
        context = self.parser.parse(
            raw_input=raw_input,
            cursor_position=cursor_position,
            max_results=max_results,
            metadata={
                'client_id': client_id,
                'raw_cursor_position': sum(2 if ord(char) > 0xFFFF else 1 for char in str(raw_input or '')) if cursor_position is None else cursor_position,
                **({'completion_spec': completion_spec} if isinstance(completion_spec, dict) else {}),
            },
        )
        context.resolved_target = SERVER_COMMAND_REGISTRY.resolve_completion_target(context)
        candidates = self.registry.complete(context)
        return {
            'context': context.to_dict(),
            'items': [item.to_dict() for item in candidates],
        }
