from server.application.external_tools.external_tool_client_runtime import ExternalToolClientLifecycleRuntime
from server.application.external_tools.external_tool_context_runtime import ExternalToolContextRuntime
from server.application.external_tools.external_tool_install_support import ExternalToolInstallSupport
from server.application.external_tools.external_tool_payload_builder import ExternalToolClientPayloadBuilder
from server.application.external_tools.external_tool_process_state import ExternalToolProcessState
from server.application.external_tools.external_tool_runtime_base import ExternalToolRuntimeBase


class ExternalToolRuntimeService:
    """Composition root for external tool client runtime services."""

    def __init__(
        self,
        catalog_service,
        command_execution_api,
        remote_execution_service=None,
        event_bus=None,
    ):
        self.core = ExternalToolRuntimeBase(
            catalog_service=catalog_service,
            command_execution_api=command_execution_api,
            remote_execution_service=remote_execution_service,
        )
        self.context_runtime = ExternalToolContextRuntime(self.core)
        self.install_support = ExternalToolInstallSupport(self.core)
        self.process_state = ExternalToolProcessState(self.core)
        self.payload_builder = ExternalToolClientPayloadBuilder(
            self.core,
            context_runtime=self.context_runtime,
            install_support=self.install_support,
            process_state=self.process_state,
        )
        self.client_lifecycle_runtime = ExternalToolClientLifecycleRuntime(
            self.core,
            payload_builder=self.payload_builder,
            event_bus=event_bus,
        )

    @property
    def remote_execution_service(self):
        return self.core.remote_execution_service
