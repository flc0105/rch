"""Shared external-tool service accessor for SDK and typed Control."""
from client.external_tools.service import ExternalToolClientService


class CommandExternalToolMixin:
    @property
    def external_tool_service(self) -> ExternalToolClientService:
        service = getattr(self, '_client_external_tool_service', None)
        if service is None:
            service = ExternalToolClientService(self)
            self._client_external_tool_service = service
        return service
