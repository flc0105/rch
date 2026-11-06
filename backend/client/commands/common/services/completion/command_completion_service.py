from core.command_completion.parser import CommandCompletionParser
from core.command_completion.registry import CommandCompletionRegistry

from client.commands.common.services.completion.command_completion_providers import (
    CdDirectoryCommandCompletionProvider,
    DownloadPathCommandCompletionProvider,
    EditPathCommandCompletionProvider,
    RuntimeConfigSetCommandCompletionProvider,
)


class ClientCommandCompletionService:
    """
    client 侧 command bar 补全服务。
    """

    def __init__(self, command_host):
        self.command_host = command_host
        self.parser = CommandCompletionParser()

    def complete(self, payload: dict) -> dict:
        data = payload if isinstance(payload, dict) else {}
        context = self.parser.parse(
            raw_input=data.get('raw_input') or '',
            cursor_position=data.get('cursor_position'),
            max_results=data.get('max_results') or 50,
            metadata=data.get('metadata') if isinstance(data.get('metadata'), dict) else {},
        )
        registry = self._build_registry()
        candidates = registry.complete(context)

        return {
            'context': context.to_dict(),
            'items': [item.to_dict() for item in candidates],
        }

    def _build_registry(self):
        registry = CommandCompletionRegistry()
        registry.register(CdDirectoryCommandCompletionProvider(
            path_resolver=self.command_host.path_resolver,
            file_system_service=self.command_host.file_system_service,
        ))
        registry.register(DownloadPathCommandCompletionProvider(
            path_resolver=self.command_host.path_resolver,
            file_system_service=self.command_host.file_system_service,
        ))
        registry.register(EditPathCommandCompletionProvider(
            path_resolver=self.command_host.path_resolver,
            file_system_service=self.command_host.file_system_service,
        ))
        registry.register(RuntimeConfigSetCommandCompletionProvider(
            runtime_config_service=self.command_host.runtime_config_service,
        ))
        return registry
