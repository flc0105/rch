"""Dependencies used by Server builtins, supplied by the application assembly."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandBuiltinServices:
    background_job_service: object
    job_catalog_service: object
    artifact_service: object
    event_bus: object
    device_event_service: object
    pinned_path_store: object
    external_tool_catalog_service: object
    external_tool_runtime_service: object
    external_tool_param_preset_store: object
    interaction_broker: object
    task_store: object
    script_catalog_service: object = None
