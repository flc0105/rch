from core.command_completion.parser import CommandCompletionParser
from core.command_completion.registry import CommandCompletionRegistry
from server.application.completion.command_completion_providers import (
    ExecScriptCommandCompletionProvider,
    ExternalToolCommandCompletionProvider,
    GopinCommandCompletionProvider,
    HistoryCommandCompletionProvider,
    HttpctlCommandCompletionProvider,
    RemoteClientCommandCompletionProvider,
    AliasCommandCompletionProvider,
)


class ServerCommandCompletionService:
    """
    server 侧 command bar 补全服务。
    """

    def __init__(self, server, remote_execution_service, pinned_path_store, external_tool_catalog_service=None):
        self.server = server
        self.parser = CommandCompletionParser()
        self.registry = CommandCompletionRegistry([
            GopinCommandCompletionProvider(
                server=server,
                pinned_path_store=pinned_path_store,
            ),
            HistoryCommandCompletionProvider(
                server=server,
                command_history=server.command_history,
            ),
            AliasCommandCompletionProvider(server.alias_manager),
            HttpctlCommandCompletionProvider(),
            ExecScriptCommandCompletionProvider(
                server=server,
            ),
            ExternalToolCommandCompletionProvider(
                server=server,
                external_tool_catalog_service=external_tool_catalog_service,
            ),
            RemoteClientCommandCompletionProvider(
                remote_execution_service=remote_execution_service,
            ),
        ])

    def complete(self, client_id: str, raw_input: str = '', cursor_position: int | None = None, max_results: int = 50) -> dict:
        context = self.parser.parse(
            raw_input=raw_input,
            cursor_position=cursor_position,
            max_results=max_results,
            metadata={
                'client_id': client_id,
            },
        )
        candidates = self.registry.complete(context)
        return {
            'context': context.to_dict(),
            'items': [item.to_dict() for item in candidates],
        }
